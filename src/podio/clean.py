"""Clean the raw per-speaker takes of an episode into prepped takes.

Measures each take, resolves its chain, renders it, and brings it to the
working level by a single gain. Censoring is a separate stage.
"""

import shutil
import sys
import tempfile
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path

from . import config as config_module
from . import ffmpeg
from .levels import GainMatch, Measured, gain_match
from .stages import build_chain

#: Repo root, from src/podio/clean.py. Where the tool-level defaults live
#: (rigs, wordlist) — this tool is run in place, not installed.
ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Result:
    take: config_module.Take
    chain: str
    measured: Measured
    gain: GainMatch
    output: Path


def process(
    take: config_module.Take,
    episode: config_module.Episode,
    models_dir: Path,
    audition: ffmpeg.Audition,
    workdir: Path,
    dry_run: bool,
) -> Result:
    floor = ffmpeg.parse_noise_floor(
        ffmpeg.run_stdout(ffmpeg.analyse_command(take.source, audition))
    )
    measured = Measured(floor_db=floor)
    chain = build_chain(take.chain, measured, models_dir)
    suffix = "_audition" if audition else "_prepped"
    output = take.source.parent / f"{take.name}{suffix}.wav"
    report(f"{take.name:6} floor {floor:7.1f} dB  {ffmpeg.WORKING_RATE} Hz")

    if dry_run:
        report(f"{take.name:6} chain {chain}")
        return Result(take, chain, measured, GainMatch(0.0, floor, False), output)

    working = workdir / f"{take.name}.wav"
    integrated, peak = ffmpeg.parse_loudness(
        ffmpeg.run(ffmpeg.render_command(take.source, chain, working, audition))
    )
    measured = replace(measured, integrated_lufs=integrated, true_peak_db=peak)
    gain = gain_match(measured, episode.working_level_db, episode.peak_ceiling_db)
    report(
        f"{take.name:6} chain I {integrated:6.1f} LUFS  TP {peak:5.1f} dB"
        f"  gain {gain.gain_db:+.1f} dB  ->  TP {gain.resulting_peak_db:5.1f} dB"
    )
    if gain.clamped:
        report(
            f"{take.name:6} WARN  gain clamped at the peak ceiling; this take lands "
            f"{episode.working_level_db - (integrated + gain.gain_db):.1f} LU under the "
            f"working level. Set limiter = true for this take, or lower "
            f"working_level_db."
        )

    ffmpeg.run(
        ffmpeg.apply_gain_command(
            working, output, gain.gain_db, take.limiter, episode.peak_ceiling_db
        )
    )
    report(f"{take.name:6} wrote {output.name}")
    return Result(take, chain, measured, gain, output)


def write_sidecar(path: Path, episode: config_module.Episode, results: list[Result]):
    lines = [
        f"# written by podio at {datetime.now(timezone.utc).isoformat()}",
        "# a record of one run; never read back as input",
        f"working_level_db = {episode.working_level_db}",
        f"peak_ceiling_db = {episode.peak_ceiling_db}",
        f"working_rate_hz = {ffmpeg.WORKING_RATE}",
    ]
    for r in results:
        lines += [
            "",
            f"[{r.take.name}]",
            f'source = "{r.take.source.name}"',
            f'output = "{r.output.name}"',
            f'chain = "{r.chain}"',
            f"noise_floor_db = {r.measured.floor_db:.2f}",
        ]
        if r.measured.integrated_lufs is not None:
            lines += [
                f"integrated_lufs = {r.measured.integrated_lufs}",
                f"true_peak_db = {r.measured.true_peak_db}",
                f"gain_db = {r.gain.gain_db:.2f}",
                f"resulting_peak_db = {r.gain.resulting_peak_db:.2f}",
                f"clamped = {str(r.gain.clamped).lower()}",
                f"limiter = {str(r.take.limiter).lower()}",
            ]
    path.write_text("\n".join(lines) + "\n")


def report(message: str):
    print(message, file=sys.stderr)


def select_takes(
    takes: list[config_module.Take], wanted: list[str], config: Path
) -> list[config_module.Take]:
    """The takes named on the command line, or all of them if none were named.

    A name that matches nothing is an error: it is almost always a filename
    where a take name belongs, so the message says which names there are.
    """
    if not wanted:
        return takes
    chosen = [t for t in takes if t.name in wanted]
    if not chosen:
        raise ValueError(
            f"no take named {', '.join(wanted)} in {config} "
            f"(takes are: {', '.join(t.name for t in takes)})"
        )
    return chosen


def clean_all(args) -> tuple[config_module.Episode, list[Result]]:
    """Clean every requested take and record what was measured.

    Raises ValueError or RuntimeError; the command wrappers turn those into an
    exit code and a message.
    """
    if not shutil.which("ffmpeg"):
        raise RuntimeError("ffmpeg is not on PATH")

    episode = config_module.load_episode(args.config, args.rigs)
    audition = ffmpeg.parse_range(args.audition) if args.audition else None
    takes = select_takes(episode.takes, args.takes, args.config)

    with tempfile.TemporaryDirectory(prefix="podio_") as tmp:
        results = [
            process(t, episode, args.models, audition, Path(tmp), args.dry_run)
            for t in takes
        ]

    if not args.dry_run:
        sidecar = args.config.parent / "audio.analysis.toml"
        write_sidecar(sidecar, episode, results)
        report(f"       wrote {sidecar.name}")
    return episode, results


def clean_episode(args) -> int:
    """Clean every requested take of an episode. Arguments come from the CLI."""
    try:
        clean_all(args)
    except (ValueError, RuntimeError) as error:
        report(f"error: {error}")
        return 1
    return 0
