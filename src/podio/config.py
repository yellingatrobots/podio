"""Two config layers: a rig, which is stable, and an episode, which is not.

A rig file holds one speaker's full ordered chain — every stage in it, with the
ones they don't normally need switched off. An episode says which rig each take
uses and flips or tweaks whatever this recording's conditions demand.
"""

import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

TAKE_KEYS = {"file", "rig"}
#: What podio itself writes into an episode directory. Never a take.
OUTPUT_SUFFIXES = ("_prepped", "_censored", "_audition")
#: Take sub-tables that configure something other than a stage of the chain,
#: and so must not be matched against the rig's stage names.
NON_STAGE_TABLES = {"censor"}

Spec = dict[str, Any]


@dataclass(frozen=True)
class Censor:
    """Whether and how a take gets censored. Overridable per take."""

    enabled: bool = True
    #: None means the wordlist shipped with the tool.
    wordlist: Path | None = None


@dataclass(frozen=True)
class Take:
    name: str
    source: Path
    chain: list[Spec]
    censor: Censor


@dataclass(frozen=True)
class Episode:
    takes: list[Take]


def stub_toml(episode_dir: Path, rigs_dir: Path) -> str:
    """An audio.toml for the takes sitting in `episode_dir`.

    Every .wav that isn't something podio wrote becomes a take, pointed at the
    rig named after it where one exists. A take whose rig is missing is still
    listed — with a comment, because that is a decision for whoever recorded it,
    not one to guess at.
    """
    takes = sorted(
        p for p in Path(episode_dir).glob("*.wav")
        if not p.stem.endswith(OUTPUT_SUFFIXES)
    )
    if not takes:
        raise ValueError(f"no .wav takes found in {episode_dir}")

    rigs = {p.stem for p in Path(rigs_dir).glob("*.toml")}
    lines = [
        "# Written by podio. Adjust and re-run.",
    ]
    for take in takes:
        lines += ["", f"[takes.{take.stem}]", f'file = "{take.name}"']
        if take.stem in rigs:
            lines.append(f'rig  = "{take.stem}"')
        else:
            lines += [
                f'rig  = "{take.stem}"'
                f"  # no rig {take.stem!r} in {rigs_dir}; create it or point at another",
            ]
    return "\n".join(lines) + "\n"


def scaffold(config_path: Path, rigs_dir: Path, *, ask) -> bool:
    """Offer to write a stub config. Returns whether one was written.

    `ask` is passed the proposed contents and answers yes or no, so the decision
    stays with the caller and this stays testable.
    """
    config_path = Path(config_path)
    if config_path.exists():
        return False

    proposed = stub_toml(config_path.parent, rigs_dir)
    if not ask(proposed):
        return False

    config_path.write_text(proposed)
    return True


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


def _read(path: Path, what: str) -> dict[str, Any]:
    if not path.exists():
        raise ValueError(f"no {what} at {path}")
    return tomllib.loads(path.read_text())


def load_episode(config_path: Path, rigs_dir: Path) -> Episode:
    episode = _read(config_path, "episode config")
    takes_table = episode.get("takes", {})
    if not takes_table:
        raise ValueError(f"{config_path} defines no takes")

    censor = _load_censor(episode.get("censor", {}), Censor(), config_path.parent)
    takes = [
        _load_take(name, table, config_path.parent, rigs_dir, censor)
        for name, table in takes_table.items()
    ]
    return Episode(takes=takes)


def _load_censor(table: Spec, inherited: Censor, episode_dir: Path) -> Censor:
    """Patch `inherited` with a [censor] table. Episode patches the defaults,
    a take patches the episode."""
    wordlist = table.get("wordlist")
    return Censor(
        enabled=bool(table.get("enabled", inherited.enabled)),
        wordlist=episode_dir / wordlist if wordlist else inherited.wordlist,
    )


def _load_take(
    name: str, table: Spec, episode_dir: Path, rigs_dir: Path, censor: Censor
) -> Take:
    for key in table:
        if key not in TAKE_KEYS and not isinstance(table[key], dict):
            raise ValueError(
                f"take {name!r}: unknown setting {key!r}; "
                f"expected one of {', '.join(sorted(TAKE_KEYS))} or a stage override"
            )

    rig_name = table.get("rig", name)
    rig = _read(rigs_dir / f"{rig_name}.toml", f"rig {rig_name!r}")
    overrides = {
        k: v
        for k, v in table.items()
        if isinstance(v, dict) and k not in NON_STAGE_TABLES
    }

    return Take(
        name=name,
        source=episode_dir / table["file"],
        chain=merge_chain(rig.get("stage", []), overrides),
        censor=_load_censor(table.get("censor", {}), censor, episode_dir),
    )


#: audio.toml's name, looked for beside each file podio is given.
EPISODE_CONFIG = "audio.toml"
EPISODE_KEYS = {"censor", "takes"}
CENSOR_KEYS = {"wordlist"}
FILE_TAKE_KEYS = {"rig"}


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
    _reject_unknown(settings, FILE_TAKE_KEYS, config_path, f"[takes.{name}] ")
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

    wav = media.with_suffix(".wav")
    censor = _load_censor(censor_table, Censor(), directory)
    return Take(
        name=name,
        source=wav if wav.exists() else media,
        chain=merge_chain(tomllib.loads(rig_path.read_text()).get("stage", []), overrides),
        censor=_load_censor(take_censor, censor, directory),
    )


def _reject_unknown(table: Spec, allowed: set[str], path: Path, where: str) -> None:
    unknown = sorted(set(table) - allowed)
    if unknown:
        raise ValueError(
            f"{path}: {where}unknown setting {', '.join(unknown)}; "
            f"expected {', '.join(sorted(allowed))}"
        )
