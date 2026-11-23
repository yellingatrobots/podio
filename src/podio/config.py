"""Two config layers: a rig, which is stable, and an episode, which is not.

A rig file holds one speaker's full ordered chain — every stage in it, with the
ones they don't normally need switched off. An episode's optional audio.toml
says which rig a take uses and flips or tweaks whatever this recording's
conditions demand.
"""

import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .stages import build_stage

#: audio.toml's name, looked for beside each file podio is given.
EPISODE_CONFIG = "audio.toml"
EPISODE_KEYS = {"censor", "takes"}
CENSOR_KEYS = {"wordlist"}
TAKE_KEYS = {"rig", "audio_delay_frames"}
#: Take sub-tables that configure something other than a stage of the chain,
#: and so must not be matched against the rig's stage names.
NON_STAGE_TABLES = {"censor"}

Spec = dict[str, Any]


@dataclass(frozen=True)
class Censor:
    """How a take gets censored. Overridable per take."""

    #: None means the wordlist shipped with the tool.
    wordlist: Path | None = None


@dataclass(frozen=True)
class Take:
    name: str
    source: Path
    chain: list[Spec]
    censor: Censor
    #: Frames to hold the audio back against the picture; negative brings it
    #: forward. Corrects a rig whose audio runs ahead of its video.
    audio_delay_frames: int = 0


def merge_chain(rig_chain: list[Spec], overrides: dict[str, Spec]) -> list[Spec]:
    """Patch a rig's chain with a take's overrides, keeping the rig's order."""
    by_name = {spec["name"] for spec in rig_chain}
    unknown = set(overrides) - by_name
    if unknown:
        raise ValueError(
            f"cannot override {', '.join(sorted(unknown))}: not in this rig's chain "
            f"({', '.join(spec['name'] for spec in rig_chain)})"
        )
    return [{**spec, **overrides.get(spec["name"], {})} for spec in rig_chain]


def _load_censor(table: Spec, inherited: Censor, episode_dir: Path) -> Censor:
    """Patch `inherited` with a [censor] table. Episode patches the defaults,
    a take patches the episode."""
    wordlist = table.get("wordlist")
    return Censor(wordlist=episode_dir / wordlist if wordlist else inherited.wordlist)


def load_take(media: Path, rigs_dir: Path, rig: str | None = None) -> Take:
    """The take `media` is, configured by the audio.toml beside it, if any.

    The take is named after the file. Its rig is `rig` when given, else the
    one audio.toml's [takes.NAME] names, else the one named after the file. A .wav with the same name beside
    a video is the take's audio; the video then only supplies the picture.
    """
    media = Path(media)
    name = media.stem
    directory = media.parent
    config_path = directory / EPISODE_CONFIG
    episode = tomllib.loads(config_path.read_text()) if config_path.exists() else {}

    _reject_unknown(episode, EPISODE_KEYS, config_path, "")
    censor_table = episode.get("censor", {})
    _reject_unknown(censor_table, CENSOR_KEYS, config_path, "[censor] ")
    table = episode.get("takes", {}).get(name, {})
    settings = {k: v for k, v in table.items() if not isinstance(v, dict)}
    _reject_unknown(settings, TAKE_KEYS, config_path, f"[takes.{name}] ")
    take_censor = table.get("censor", {})
    _reject_unknown(take_censor, CENSOR_KEYS, config_path, f"[takes.{name}.censor] ")

    rig_name = rig or table.get("rig", name)
    rig_path = rigs_dir / f"{rig_name}.toml"
    if not rig_path.exists():
        rigs = ", ".join(sorted(p.stem for p in rigs_dir.glob("*.toml")))
        how = "" if rig else (
            f"; name the file after a rig, or set [takes.{name}] rig = \"...\" "
            f"in {directory / EPISODE_CONFIG}"
        )
        raise ValueError(f"no rig {rig_name!r} for {media.name} (rigs: {rigs}){how}")
    overrides = {
        k: v for k, v in table.items() if isinstance(v, dict) and k not in NON_STAGE_TABLES
    }

    rig_config = tomllib.loads(rig_path.read_text())
    delay = table.get("audio_delay_frames", rig_config.get("audio_delay_frames", 0))
    if type(delay) is not int:
        raise ValueError(
            f"audio_delay_frames for {media.name} must be a whole number of "
            f"frames, not {delay!r}"
        )

    wav = media.with_suffix(".wav")
    censor = _load_censor(censor_table, Censor(), directory)
    return Take(
        name=name,
        source=wav if wav.exists() else media,
        chain=merge_chain(rig_config.get("stage", []), overrides),
        censor=_load_censor(take_censor, censor, directory),
        audio_delay_frames=delay,
    )


def _reject_unknown(table: Spec, allowed: set[str], path: Path, where: str) -> None:
    unknown = sorted(set(table) - allowed)
    if unknown:
        raise ValueError(
            f"{path}: {where}unknown setting {', '.join(unknown)}; "
            f"expected {', '.join(sorted(allowed))}"
        )


#: Files a take can be. A video and a .wav of the same name are one take.
MEDIA_SUFFIXES = {".wav", ".mp4", ".mov", ".mkv", ".m4v"}
#: What podio itself writes beside the takes. Never a take.
WRITTEN_SUFFIXES = ("_prepped", "_cleaned", "_muxed")
WRITTEN_STEMS = {"censored", "normalized"}


def find_takes(directory: Path) -> list[Path]:
    """The takes in `directory`, one file per name, the video before its .wav."""
    by_name: dict[str, Path] = {}
    for path in sorted(Path(directory).iterdir()):
        stem = path.stem
        if (path.suffix.lower() not in MEDIA_SUFFIXES or stem in WRITTEN_STEMS
                or stem.endswith(WRITTEN_SUFFIXES)):
            continue
        if stem not in by_name or by_name[stem].suffix.lower() == ".wav":
            by_name[stem] = path
    return [by_name[stem] for stem in sorted(by_name)]


def _toml(value: Any) -> str:
    """One TOML value, for the few kinds a rig holds."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    if isinstance(value, int | float):
        return repr(value)
    if isinstance(value, str):
        return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'
    if isinstance(value, list):
        return "[" + ", ".join(_toml(v) for v in value) + "]"
    if isinstance(value, dict):
        return "{ " + ", ".join(f"{k} = {_toml(v)}" for k, v in value.items()) + " }"
    raise TypeError(f"no TOML form for {value!r}")


TEMPLATE_HEADER = f"""\
# {EPISODE_CONFIG}: what this episode changes in the rigs. Written by podio init.
#
# Every setting is commented out at the value its take gets without it: the
# rig's, or the stage's own where the rig says nothing. Uncomment a setting
# and change it to change that take; a commented one has no effect. A stage
# table changes only the keys under it.

# [censor]
# The wordlist podio ships is the default. For another, beside this file:
#   wordlist = "words.toml"
"""


def episode_template(media: list[Path], rigs_dir: Path) -> str:
    """An audio.toml for the takes `media`, every setting commented at its default."""
    rigs = ", ".join(sorted(p.stem for p in rigs_dir.glob("*.toml")))
    blocks = [TEMPLATE_HEADER]
    for path in media:
        name = Path(path).stem
        lines = [f"# [takes.{name}]"]
        rig_path = rigs_dir / f"{name}.toml"
        if not rig_path.exists():
            lines.append(f'# rig = ""   # no rig named {name}; one of: {rigs}')
            blocks.append("\n".join(lines) + "\n")
            continue
        rig = tomllib.loads(rig_path.read_text())
        lines += [
            f'# rig = "{name}"   # one of: {rigs}',
            f"# audio_delay_frames = {rig.get('audio_delay_frames', 0)}",
            "",
            f"# [takes.{name}.censor]",
            "# The episode's [censor] wordlist is the default. For this take only:",
            f'#   wordlist = "{name}_words.toml"',
        ]
        for spec in rig.get("stage", []):
            stage = build_stage(spec).model_dump(exclude={"name"})
            lines += ["", f"# [takes.{name}.{spec['name']}]"]
            lines += [f"# {key} = {_toml(value)}" for key, value in stage.items()]
        blocks.append("\n".join(lines) + "\n")
    return "\n".join(blocks)
