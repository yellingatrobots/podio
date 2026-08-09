"""Recording a bumper from a live capture device.

Everywhere else podio reads files that already exist. This is the one place it
opens a microphone, and it does so through OpenAL on every platform.

That is a deliberate choice, and the reason is worth keeping: ffmpeg's
`avfoundation` input — the obvious way to record on macOS, and the one every
recipe on the internet gives — **loses audio**. Its capture delegate holds a
single buffer slot and releases whatever is still sitting there when the next
buffer arrives (`libavdevice/avfoundation.m`, `didOutputSampleBuffer`), so
anything the reader has not collected in time is dropped on the floor. There is
no queue and no option that adds one; `drop_late_frames` only reaches the video
path. Measured here, it lost 11–17% of every recording, in gaps of a few
milliseconds tens of times a second. The samples either side get spliced
together, and each splice is a click — audible only once there is signal, which
is what makes it look like a microphone fault rather than a capture bug.

OpenAL reads through a ring buffer instead, and measured 0.02% over the same
recordings. It also names its devices rather than numbering them, and names are
what survive a device being plugged in — an index is a position in a list that
changes when a pair of headphones connects.

On Linux, `pulse` and `alsa` stay as fallbacks: they do not share the
avfoundation defect, and OpenAL may find nothing to talk to on a headless box.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from . import ffmpeg
from .ffmpeg import WORKING_RATE

#: The heading `-list_devices` prints before an OpenAL listing.
OPENAL_HEADING = "List of OpenAL capture devices"
#: A device in that listing. ffmpeg's log prefix, then the name indented under
#: the heading — the indent is what separates a device from the heading itself
#: and from any other line ffmpeg logs.
OPENAL_DEVICE = re.compile(r"^\[[^\]]*\]\s\s+(\S.*?)\s*$")
#: A device in a `-sources` listing: `printf("%c %s [%s] (%s)")`, where the
#: leading character is `*` for the system default and a space otherwise.
SOURCE = re.compile(r"^([* ]) (\S+) \[(.*)\] \(([^)]*)\)\s*$")
#: A line of `ffmpeg -devices`: ` D  openal    OpenAL audio capture device`.
#: The two flag columns are the letter or a space — the dots in the legend above
#: them are what keeps ` D. = Demuxing supported` from reading as a device. `D`
#: is demuxing, and a device podio can record from must have it.
BACKEND = re.compile(r"^ ([D ])([E ]) (\S+)\s")


@dataclass(frozen=True)
class Device:
    """One capture device: podio's number for it, ffmpeg's name, and yours."""

    index: int
    #: What `-i` wants.
    spec: str
    #: What a human recognises the device by.
    name: str
    is_default: bool = False


def _parse_openal(output: str) -> list[Device]:
    devices: list[Device] = []
    reached_listing = False
    for line in output.splitlines():
        if OPENAL_HEADING in line:
            reached_listing = True
            continue
        if not reached_listing:
            continue
        match = OPENAL_DEVICE.match(line)
        if not match:
            break
        devices.append(Device(len(devices), match.group(1), match.group(1)))
    if not reached_listing:
        raise ValueError(
            f"ffmpeg printed no OpenAL listing:\n\n{output.strip()}"
        )
    return devices


def _parse_sources(output: str) -> list[Device]:
    """Read a `-sources` listing, which reports its own failure and exits 0."""
    if "Cannot list sources" in output:
        raise ValueError(output.strip())
    devices: list[Device] = []
    for line in output.splitlines():
        match = SOURCE.match(line)
        if not match:
            continue
        default, spec, description, media = match.groups()
        if "audio" not in media.split(", "):
            continue
        devices.append(
            Device(len(devices), spec, description or spec, default == "*")
        )
    return devices


@dataclass(frozen=True)
class Backend:
    """One way in to the machine's microphones, and how to ask it what it has."""

    #: The ffmpeg input format, for `-f`.
    format: str
    #: Args that make ffmpeg enumerate. It is not a successful run either way:
    #: listing ends by failing to open the input it was never given, and
    #: `-sources` prints its own error rather than returning one.
    list_arguments: tuple[str, ...]
    parse: Callable[[str], list[Device]]
    #: What `-i` gets when nobody chose a device — each backend spells its own
    #: "whatever the system is using" differently, and OpenAL spells it empty.
    default_device: str
    #: How to ask the device for the shape podio wants, so nothing has to be
    #: converted afterwards. Empty where the backend negotiates it itself.
    input_arguments: tuple[str, ...] = ()

    def list_command(self) -> list[str]:
        return [ffmpeg.executable(), "-hide_banner", *self.list_arguments]


OPENAL = Backend(
    format="openal",
    list_arguments=("-f", "openal", "-list_devices", "true", "-i", ""),
    parse=_parse_openal,
    default_device="",
    # Asked for at the working rate in mono, so the capture needs no resampling
    # and no downmix. `sample_size` is capped at 16 by OpenAL itself, which is
    # the one thing given up by not using avfoundation — and a complete 16-bit
    # recording beats a 24-bit one with holes in it.
    input_arguments=("-channels", "1", "-sample_rate", str(WORKING_RATE),
                     "-sample_size", "16"),
)
PULSE = Backend(
    format="pulse",
    list_arguments=("-sources", "pulse"),
    parse=_parse_sources,
    default_device="default",
)
ALSA = Backend(
    format="alsa",
    list_arguments=("-sources", "alsa"),
    parse=_parse_sources,
    default_device="default",
)

#: In preference order. OpenAL everywhere, because it is the one that does not
#: drop audio; pulse and alsa are there for a Linux box where OpenAL finds
#: nothing. avfoundation is deliberately absent — see the module docstring.
BACKENDS = {
    "darwin": (OPENAL,),
    "linux": (OPENAL, PULSE, ALSA),
}


def parse_backends(output: str) -> set[str]:
    """The input formats this ffmpeg was built with, from `ffmpeg -devices`."""
    return {
        match.group(3)
        for match in map(BACKEND.match, output.splitlines())
        if match and match.group(1) == "D"
    }


def backend_for(platform: str, available: set[str]) -> list[Backend]:
    """The backends to try, in order, for this platform and this ffmpeg build."""
    known = next(
        (backends for prefix, backends in BACKENDS.items()
         if platform.startswith(prefix)),
        None,
    )
    if known is None:
        raise ValueError(
            f"podio does not know how to record on {platform!r}; it records "
            f"through {', '.join(sorted(BACKENDS))}"
        )
    usable = [backend for backend in known if backend.format in available]
    if not usable:
        raise ValueError(
            f"this ffmpeg cannot record on {platform!r}: it was built without "
            f"{' or '.join(b.format for b in known)}. podio needs an ffmpeg "
            f"with OpenAL — check `ffmpeg -devices`."
        )
    return usable


def resolve_device(
    chosen: str | None, devices: list[Device], backend: Backend
) -> str:
    """Turn what was typed into the device name ffmpeg's `-i` takes.

    A bare number is one of podio's own, as printed by `podio devices`. Anything
    else is passed through untouched, because a listing is not exhaustive — an
    alsa card that was never advertised still has to be reachable by name.
    """
    if chosen is None:
        return backend.default_device
    if not chosen.isdigit():
        return chosen
    index = int(chosen)
    for device in devices:
        if device.index == index:
            return device.spec
    raise ValueError(
        f"there is no device {index}; `podio devices` lists what there is"
    )


def record_command(backend: Backend, device: str, destination) -> list[str]:
    """Record one bumper: mono, at the working rate, 24-bit as a take would be.

    No `-y`. Every other output podio writes can be rendered again from its
    inputs; a recording cannot, so overwriting one is checked for before this
    command is ever built.
    """
    return [
        ffmpeg.executable(), "-hide_banner",
        "-f", backend.format,
        *backend.input_arguments,
        "-i", device,
        "-ac", "1",
        "-ar", str(WORKING_RATE),
        "-c:a", "pcm_s24le",
        str(Path(destination)),
    ]


def enumerate_devices(
    backends: list[Backend], probe: Callable[[list[str]], str]
) -> tuple[Backend, list[Device]]:
    """Ask each backend in turn, taking the first that finds a microphone.

    Falling through matters on Linux: pulse is compiled in whether or not a
    sound server is running, so "pulse is available" is not the same claim as
    "pulse can hear anything", and only asking it tells them apart.
    """
    refusals = []
    for backend in backends:
        try:
            devices = backend.parse(probe(backend.list_command()))
        except ValueError as error:
            refusals.append(f"{backend.format}: {error}")
            continue
        if devices:
            return backend, devices
        refusals.append(f"{backend.format}: listed no capture devices")
    raise ValueError(
        "found nothing to record from. Each way in was asked:\n  "
        + "\n  ".join(refusals)
    )


def discover(probe: Callable[[list[str]], str] = ffmpeg.probe):
    """What this machine can record from, and how to reach it."""
    installed = parse_backends(probe([ffmpeg.executable(), "-hide_banner", "-devices"]))
    return enumerate_devices(backend_for(sys.platform, installed), probe)
