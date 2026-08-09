import pytest

from podio.capture import (
    ALSA,
    OPENAL,
    PULSE,
    Device,
    backend_for,
    enumerate_devices,
    parse_backends,
    record_command,
    resolve_device,
)

# `ffmpeg -f openal -list_devices true -i ""`, on stderr. The run always ends
# in the error of opening the input that was never given.
OPENAL_LISTING = """\
[in#0 @ 0x916c34000] List of OpenAL capture devices on this system:
[in#0 @ 0x916c34000]   airmax
[in#0 @ 0x916c34000]   USB Digital Audio
[in#0 @ 0x916c34000]   RØDE PodMic USB
Error opening input file .
"""

# `ffmpeg -sources pulse`, on stdout: "%c %s [%s] (%s)", the leading character
# marking the system default.
PULSE_LISTING = """\
Auto-detected sources for pulse:
* alsa_input.pci-0000_00_1f.3.analog-stereo [Built-in Audio Analog Stereo] (audio)
  alsa_input.usb-RODE_PodMic_USB-00.mono-fallback [RØDE PodMic USB] (audio)
"""

DEVICES_LISTING = """\
Devices:
 D. = Demuxing supported
 .E = Muxing supported
 ---
  E audiotoolbox    AudioToolbox output device
 D  avfoundation    AVFoundation input device
 D  lavfi           Libavfilter virtual input device
"""


def test_openal_listing_reads_the_names_under_the_heading():
    """Names, not indices: an index is a position in a list that shifts the
    moment a pair of headphones connects."""
    assert OPENAL.parse(OPENAL_LISTING) == [
        Device(0, "airmax", "airmax"),
        Device(1, "USB Digital Audio", "USB Digital Audio"),
        Device(2, "RØDE PodMic USB", "RØDE PodMic USB"),
    ]


def test_openal_listing_stops_at_the_error_it_always_ends_with():
    """Listing devices is a failed input open by design, so that trailing line
    is part of every listing and is not a device."""
    assert all("Error" not in d.name for d in OPENAL.parse(OPENAL_LISTING))


def test_openal_listing_with_no_microphones_attached():
    listing = "[in#0 @ 0x1] List of OpenAL capture devices on this system:\n"
    assert OPENAL.parse(listing) == []


def test_openal_listing_complains_when_ffmpeg_has_no_openal():
    with pytest.raises(ValueError, match="OpenAL"):
        OPENAL.parse("Unknown input format: 'openal'")


def test_sources_listing_keeps_the_name_ffmpeg_wants_and_the_one_you_read():
    """A pulse source is addressed by an unreadable identifier and recognised by
    its description, so podio needs both."""
    assert PULSE.parse(PULSE_LISTING) == [
        Device(0, "alsa_input.pci-0000_00_1f.3.analog-stereo",
               "Built-in Audio Analog Stereo", is_default=True),
        Device(1, "alsa_input.usb-RODE_PodMic_USB-00.mono-fallback",
               "RØDE PodMic USB"),
    ]


def test_sources_listing_skips_anything_that_is_not_audio():
    listing = PULSE_LISTING + "  /dev/video0 [Integrated Camera] (video)\n"
    assert [d.name for d in PULSE.parse(listing)] == [
        "Built-in Audio Analog Stereo", "RØDE PodMic USB",
    ]


def test_sources_listing_complains_when_the_server_is_not_running():
    """Pulse can be compiled in and still have nothing to talk to — the caller
    needs to know to fall back to alsa rather than show an empty list."""
    with pytest.raises(ValueError, match="Cannot list sources"):
        PULSE.parse(
            "Auto-detected sources for pulse:\n"
            "Cannot list sources: Connection refused\n"
        )


def test_parse_backends_reads_what_this_ffmpeg_was_built_with():
    assert parse_backends(DEVICES_LISTING) == {"avfoundation", "lavfi"}


def test_parse_backends_leaves_out_the_output_only_devices():
    """audiotoolbox muxes, it does not demux; it can never be a source."""
    assert "audiotoolbox" not in parse_backends(DEVICES_LISTING)


def test_backend_for_macos_is_openal_and_never_avfoundation():
    """avfoundation is the obvious choice and drops 11-17% of the audio; it is
    left out on purpose, so a mac with no OpenAL fails loudly rather than
    recording something full of clicks."""
    assert backend_for("darwin", {"openal", "avfoundation", "lavfi"}) == [OPENAL]


def test_backend_for_macos_without_openal_refuses_rather_than_fall_back():
    with pytest.raises(ValueError, match="OpenAL"):
        backend_for("darwin", {"avfoundation", "lavfi"})


def test_backend_for_linux_keeps_pulse_and_alsa_behind_openal():
    """OpenAL first everywhere, but a headless box may have nothing for it to
    talk to, and pulse and alsa do not share the avfoundation defect."""
    assert backend_for("linux", {"openal", "pulse", "alsa"}) == [OPENAL, PULSE, ALSA]


def test_backend_for_linux_without_openal_still_records():
    assert backend_for("linux", {"alsa"}) == [ALSA]


def test_backend_for_a_platform_with_nothing_to_record_through():
    with pytest.raises(ValueError, match="record"):
        backend_for("linux", {"lavfi"})


def test_backend_for_an_unsupported_platform_says_so():
    with pytest.raises(ValueError, match="win32"):
        backend_for("win32", {"dshow"})


DEVICES = [
    Device(0, "alsa_input.pci-0000", "Built-in Audio", is_default=True),
    Device(1, "alsa_input.usb-RODE", "RØDE PodMic USB"),
]


def test_resolve_device_takes_the_index_that_podio_devices_printed():
    """The whole point of the numbering: a pulse identifier is not typeable."""
    assert resolve_device("1", DEVICES, PULSE) == "alsa_input.usb-RODE"


def test_resolve_device_defaults_to_the_one_the_system_calls_default():
    assert resolve_device(None, DEVICES, PULSE) == "default"


def test_resolve_device_lets_openal_pick_its_own_default():
    """OpenAL spells "the system's own microphone" as an empty input."""
    assert resolve_device(None, [Device(0, "RØDE", "RØDE")], OPENAL) == ""


def test_resolve_device_passes_a_real_device_name_straight_through():
    """An alsa card that pulse never listed still has to be reachable."""
    assert resolve_device("hw:1,0", DEVICES, ALSA) == "hw:1,0"


def test_resolve_device_rejects_an_index_that_was_not_listed():
    with pytest.raises(ValueError, match="no device 7"):
        resolve_device("7", DEVICES, PULSE)


ALSA_LISTING = """\
Auto-detected sources for alsa:
  hw:CARD=PodMic,DEV=0 [RØDE PodMic USB] (audio)
"""


def test_enumerate_falls_through_to_alsa_when_no_sound_server_is_running():
    """Pulse is compiled in whether or not anything is listening, so being
    available is not the same as being able to hear — only asking tells them
    apart, and a machine with no pulse server still has a microphone."""
    answers = {
        ("-sources", "pulse"): "Auto-detected sources for pulse:\n"
                               "Cannot list sources: Connection refused\n",
        ("-sources", "alsa"): ALSA_LISTING,
    }
    backend, devices = enumerate_devices(
        [PULSE, ALSA], lambda cmd: answers[tuple(cmd[-2:])]
    )
    assert backend is ALSA
    assert [d.name for d in devices] == ["RØDE PodMic USB"]


def test_enumerate_prefers_pulse_when_it_answers():
    backend, _ = enumerate_devices([PULSE, ALSA], lambda cmd: PULSE_LISTING)
    assert backend is PULSE


def test_enumerate_reports_what_every_backend_said_when_none_worked():
    """One line saying "no devices" would hide which of the two failed and why."""
    with pytest.raises(ValueError) as failure:
        enumerate_devices(
            [PULSE, ALSA],
            lambda cmd: "Auto-detected sources for x:\nCannot list sources: no\n",
        )
    assert "pulse" in str(failure.value) and "alsa" in str(failure.value)


def test_record_command_captures_mono_at_the_working_rate():
    cmd = record_command(OPENAL, "RØDE PodMic USB", "bumper.wav")
    assert cmd[cmd.index("-f") + 1] == "openal"
    assert cmd[cmd.index("-i") + 1] == "RØDE PodMic USB"
    assert cmd[cmd.index("-ac") + 1] == "1"
    assert cmd[cmd.index("-ar") + 1] == "48000"
    assert cmd[cmd.index("-c:a") + 1] == "pcm_s24le"
    assert cmd[-1] == "bumper.wav"


def test_record_command_asks_the_device_for_the_shape_it_wants():
    """Captured at the working rate in mono, so the recording is not resampled
    or downmixed after the fact."""
    cmd = record_command(OPENAL, "RØDE PodMic USB", "bumper.wav")
    opened = cmd[:cmd.index("-i")]
    assert opened[opened.index("-sample_rate") + 1] == "48000"
    assert opened[opened.index("-channels") + 1] == "1"


def test_record_command_uses_the_backend_it_was_given():
    cmd = record_command(PULSE, "default", "bumper.wav")
    assert cmd[cmd.index("-f") + 1] == "pulse"


def test_record_command_does_not_overwrite_behind_your_back():
    """A recording is the one thing podio makes that it cannot make again, so
    `-y` here would be a way to lose a bumper to a repeated command."""
    assert "-y" not in record_command(OPENAL, "RØDE PodMic USB", "bumper.wav")
