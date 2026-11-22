"""Clean the raw per-speaker takes of an episode into prepped takes.

Measures each take, resolves its chain, renders it, and brings it to
delivery loudness (-16 LUFS, under -1 dBTP). Censoring is a separate stage.
"""

import shutil
import sys
import tempfile
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path

from . import config as config_module
from . import ffmpeg
from .levels import TARGET_LUFS, TRUE_PEAK_LIMIT_DB, Measured
from .master import Leveled, Loudness, level
from .stages import build_chain


@dataclass(frozen=True)
class Result:
    take: config_module.Take
    chain: str
    measured: Measured
    #: None on a dry run, which renders nothing.
    leveled: Leveled | None
    output: Path


def process(
    take: config_module.Take,
    models_dir: Path,
    audition: ffmpeg.Audition,
    workdir: Path,
    dry_run: bool,
    output_dir: Path,
) -> Result:
    floor = ffmpeg.parse_noise_floor(
        ffmpeg.run_stdout(ffmpeg.analyse_command(take.source, audition))
    )
    measured = Measured(floor_db=floor)
    chain = build_chain(take.chain, measured, models_dir)
    suffix = "_audition" if audition else "_prepped"
    output = output_dir / f"{take.name}{suffix}.wav"
    report(f"{take.name:6} floor {floor:7.1f} dB  {ffmpeg.WORKING_RATE} Hz")

    if dry_run:
        report(f"{take.name:6} chain {chain}")
        return Result(take, chain, measured, None, output)

    working = workdir / f"{take.name}.wav"
    integrated, peak = ffmpeg.parse_loudness(
        ffmpeg.run(ffmpeg.render_command(take.source, chain, working, audition))
    )
    measured = replace(measured, integrated_lufs=integrated, true_peak_db=peak)
    leveled = level(working, Loudness(integrated, peak), output)
    out = leveled.rendered
    report(
        f"{take.name:6} chain I {integrated:6.1f} LUFS  TP {peak:5.1f} dB"
        f"  gain {leveled.gain_db:+.1f} dB"
        f"  ->  I {out.integrated_lufs:6.1f} LUFS  TP {out.true_peak_db:5.1f} dB"
    )
    report(f"{take.name:6} wrote {output.name}")
    return Result(take, chain, measured, leveled, output)


def write_sidecar(path: Path, results: list[Result]):
    lines = [
        f"# written by podio at {datetime.now(timezone.utc).isoformat()}",
        "# a record of one run; never read back as input",
        f"target_lufs = {TARGET_LUFS}",
        f"true_peak_limit_db = {TRUE_PEAK_LIMIT_DB}",
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
        if r.leveled is not None:
            lines += [
                f"integrated_lufs = {r.measured.integrated_lufs}",
                f"true_peak_db = {r.measured.true_peak_db}",
                f"gain_db = {r.leveled.gain_db:.2f}",
                f"delivered_lufs = {r.leveled.rendered.integrated_lufs}",
                f"delivered_true_peak_db = {r.leveled.rendered.true_peak_db}",
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


def clean_all(
    args, output_dir: Path | None = None
) -> tuple[config_module.Episode, list[Result]]:
    """Clean every requested take and record what was measured.

    Raises ValueError or RuntimeError; the command wrappers turn those into an
    exit code and a message.
    """
    if not shutil.which("ffmpeg"):
        raise RuntimeError("ffmpeg is not on PATH")

    episode = config_module.load_episode(args.config, args.rigs)
    audition = ffmpeg.parse_range(args.audition) if args.audition else None
    takes = select_takes(episode.takes, args.takes, args.config)
    if output_dir is None:
        output_dir = args.config.parent
    if not args.dry_run:
        output_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="podio_") as tmp:
        results = [
            process(
                t, args.models, audition, Path(tmp), args.dry_run, output_dir
            )
            for t in takes
        ]

    if not args.dry_run:
        sidecar = output_dir / "audio_analysis.toml"
        write_sidecar(sidecar, results)
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
