"""Two config layers: a rig, which is stable, and an episode, which is not.

A rig file holds one speaker's full ordered chain — every stage in it, with the
ones they don't normally need switched off. An episode says which rig each take
uses and flips or tweaks whatever this recording's conditions demand.
"""

import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

TAKE_KEYS = {"file", "rig", "limiter"}
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
    limiter: bool
    censor: Censor


@dataclass(frozen=True)
class Episode:
    working_level_db: float
    peak_ceiling_db: float
    takes: list[Take]


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
    return Episode(
        working_level_db=episode.get("working_level_db", -20.0),
        peak_ceiling_db=episode.get("peak_ceiling_db", -3.0),
        takes=takes,
    )


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
        limiter=bool(table.get("limiter", False)),
        censor=_load_censor(table.get("censor", {}), censor, episode_dir),
    )
