"""Clean one take: measure it, resolve its chain, render it, and bring it to
delivery loudness (-16 LUFS, under -1 dBTP). Censoring is a separate stage.
"""

import sys
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path

from . import ffmpeg
from .config import Take
from .deliver import Leveled, Loudness, level
from .levels import TARGET_LUFS, TRUE_PEAK_LIMIT_DB, Measured
from .stages import build_chain


@dataclass(frozen=True)
class Result:
    take: Take
    chain: str
    measured: Measured
    leveled: Leveled
    output: Path


def measure_chain(take: Take, rnnoise_models: Path) -> tuple[Measured, str]:
    """The take's noise floor, and the chain resolved against it."""
    floor = ffmpeg.parse_noise_floor(
        ffmpeg.run_stdout(ffmpeg.analyse_command(take.source))
    )
    measured = Measured(floor_db=floor)
    report(f"{take.name:6} floor {floor:7.1f} dB  {ffmpeg.WORKING_RATE} Hz")
    return measured, build_chain(take.chain, measured, rnnoise_models)


def process(take: Take, rnnoise_models: Path, workdir: Path, output: Path) -> Result:
    measured, chain = measure_chain(take, rnnoise_models)
    working = workdir / f"{take.name}_chain.wav"
    integrated, peak = ffmpeg.parse_loudness(
        ffmpeg.run(ffmpeg.render_command(take.source, chain, working))
    )
    measured = replace(measured, integrated_lufs=integrated, true_peak_db=peak)
    leveled = level(working, Loudness(integrated, peak), output)
    out = leveled.rendered
    report(
        f"{take.name:6} chain I {integrated:6.1f} LUFS  TP {peak:5.1f} dB"
        f"  gain {leveled.gain_db:+.1f} dB"
        f"  ->  I {out.integrated_lufs:6.1f} LUFS  TP {out.true_peak_db:5.1f} dB"
    )
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
            f"integrated_lufs = {r.measured.integrated_lufs}",
            f"true_peak_db = {r.measured.true_peak_db}",
            f"gain_db = {r.leveled.gain_db:.2f}",
            f"delivered_lufs = {r.leveled.rendered.integrated_lufs}",
            f"delivered_true_peak_db = {r.leveled.rendered.true_peak_db}",
        ]
    path.write_text("\n".join(lines) + "\n")


def report(message: str):
    print(message, file=sys.stderr)
