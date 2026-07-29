#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = ["pydantic>=2"]
# ///
"""Clean the raw per-speaker takes of an episode into NLE-ready WAVs.

    uv run run.py                     both takes, full length
    uv run run.py --range 21:30+45    just the bit you want to hear
    uv run run.py --dry-run           measure and report, render nothing
"""

import argparse
import os
import shutil
import sys
import tempfile
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path

import config as config_module
import ffmpeg
from levels import GainMatch, Measured, gain_match
from stages import build_chain

TOOL_DIR = Path(__file__).parent


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
    suffix = "_audition" if audition else "_clean"
    output = take.source.parent / f"{take.name}{suffix}.wav"
    report(f"{take.name:6} floor {floor:7.1f} dB")

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
        f"# written by podcast_audio at {datetime.now(timezone.utc).isoformat()}",
        "# a record of one run; never read back as input",
        f"working_level_db = {episode.working_level_db}",
        f"peak_ceiling_db = {episode.peak_ceiling_db}",
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


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "takes", nargs="*", help="only process these takes (default: all)"
    )
    parser.add_argument("-c", "--config", type=Path, default=Path("audio.toml"))
    parser.add_argument("--rigs", type=Path, default=TOOL_DIR / "rigs")
    parser.add_argument(
        "--range",
        dest="audition",
        help="render only this slice, as START+SECONDS (e.g. 21:30+45)",
    )
    parser.add_argument(
        "--models",
        type=Path,
        default=Path(os.environ.get("RNNOISE_MODELS", "")),
        help="directory of .rnnn files (default: $RNNOISE_MODELS)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="measure and print the resolved chain, but render nothing",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if not shutil.which("ffmpeg"):
        report("ffmpeg is not on PATH")
        return 1

    try:
        episode = config_module.load_episode(args.config, args.rigs)
        audition = ffmpeg.parse_range(args.audition) if args.audition else None
        takes = [t for t in episode.takes if not args.takes or t.name in args.takes]
        if not takes:
            raise ValueError(f"no take named {', '.join(args.takes)} in {args.config}")

        with tempfile.TemporaryDirectory(prefix="podcast_audio_") as tmp:
            results = [
                process(t, episode, args.models, audition, Path(tmp), args.dry_run)
                for t in takes
            ]
    except (ValueError, RuntimeError) as error:
        report(f"error: {error}")
        return 1

    if not args.dry_run:
        sidecar = args.config.parent / "audio.analysis.toml"
        write_sidecar(sidecar, episode, results)
        report(f"       wrote {sidecar.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
