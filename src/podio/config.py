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


def load_take(media: Path, rigs_dir: Path) -> Take:
    """The take `media` is, configured by the audio.toml beside it, if any.

    The take is named after the file. Its rig is the one of that name unless
    audio.toml's [takes.NAME] says otherwise. A .wav with the same name beside
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

    rig_name = table.get("rig", name)
    rig_path = rigs_dir / f"{rig_name}.toml"
    if not rig_path.exists():
        rigs = ", ".join(sorted(p.stem for p in rigs_dir.glob("*.toml")))
        raise ValueError(
            f"no rig {rig_name!r} for {media.name} (rigs: {rigs}); name the file "
            f"after a rig, or set [takes.{name}] rig = \"...\" in "
            f"{directory / EPISODE_CONFIG}"
        )
    overrides = {
        k: v for k, v in table.items() if isinstance(v, dict) and k not in NON_STAGE_TABLES
    }

    rig = tomllib.loads(rig_path.read_text())
    delay = table.get("audio_delay_frames", rig.get("audio_delay_frames", 0))
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
        chain=merge_chain(rig.get("stage", []), overrides),
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
