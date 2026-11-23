"""Prep: one source file in, the same kind of file out, ready for production.

    NAME.mp4 (or NAME.wav) ──▶ clean ──▶ -16 LUFS ──▶ detect ──▶ bleep
                           ──▶ NAME_prepped.mp4 (or NAME_prepped.wav)

Every intermediate lives in a working directory that is thrown away, unless
the caller asks to keep it. Each file is independent of the others, so they
run in parallel processes, and one failing never stops the rest.
"""

from __future__ import annotations

import multiprocessing
import shutil
import tempfile
from concurrent.futures import ProcessPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from . import censor, ffmpeg
from .clean import process, report, write_sidecar
from .config import Take, load_take
from .deliver import measure
from .levels import TARGET_LUFS, TRUE_PEAK_LIMIT_DB, meets_delivery
from .transcribe import WhisperXTranscriber
from .wordlist import WordList

OUTPUT_SUFFIX = "_prepped"


@dataclass(frozen=True)
class Job:
    take: Take
    media: Path
    output: Path
    #: None when nothing is to be bleeped.
    wordlist: Path | None
    model: str
    rnnoise_models: Path
    #: Where intermediates are kept; None throws them away.
    keep: Path | None


def output_path(media: Path) -> Path:
    return media.with_name(f"{media.stem}{OUTPUT_SUFFIX}{media.suffix}")


def plan(
    files: list[Path],
    *,
    rigs: Path,
    rig: str | None = None,
    bleep: bool,
    wordlist: Path | None,
    default_wordlist: Path,
    model: str,
    rnnoise_models: Path,
    keep_temp: Path | None,
) -> list[Job]:
    """Resolve every file's take, rig and wordlist before any work starts.

    Raises ValueError on the first file that cannot be prepped, so a typo costs
    a second rather than the minutes another file has already spent.
    """
    jobs = []
    for media in files:
        media = Path(media)
        if not media.exists():
            raise ValueError(f"no file at {media}")
        take = load_take(media, rigs, rig)
        chosen = None
        if bleep:
            chosen = wordlist or take.censor.wordlist or default_wordlist
            WordList.from_file(chosen)
        keep = keep_temp / take.name if keep_temp else None
        jobs.append(Job(take, media, output_path(media), chosen, model, rnnoise_models, keep))

    if keep_temp:
        names = [job.take.name for job in jobs]
        doubled = sorted({n for n in names if names.count(n) > 1})
        if doubled:
            raise ValueError(
                f"--keep-temp keeps each file under its name, and "
                f"{', '.join(doubled)} is given more than once"
            )
    return jobs


@contextmanager
def _workdir(keep: Path | None) -> Iterator[Path]:
    if keep:
        keep.mkdir(parents=True, exist_ok=True)
        yield keep
        return
    with tempfile.TemporaryDirectory(prefix="podio_") as tmp:
        yield Path(tmp)


def prep_one(job: Job) -> Path:
    """Prep one file and return what was written."""
    name = job.take.name
    with _workdir(job.keep) as work:
        result = process(
            job.take, job.rnnoise_models, work, work / f"{name}_cleaned.wav"
        )
        audio = result.output
        if job.wordlist:
            transcriber = WhisperXTranscriber(model_size=job.model, device="cpu", language="en")
            manifest, spans = censor.detect_into(
                audio, work, name, WordList.from_file(job.wordlist), transcriber,
                inset=0.03, min_confidence=0.0,
            )
            report(f"{name:6} detected {spans} span(s)")
            audio = censor.splice(audio, manifest, work, name)
        write_sidecar(work / "audio_analysis.toml", [result])

        frames = job.take.audio_delay_frames
        if job.media.suffix.lower() == ".wav":
            if frames:
                report(
                    f"{name:6} audio_delay_frames = {frames} not applied: "
                    f"{job.media.name} has no picture to sync to"
                )
            shutil.copyfile(audio, job.output)
        else:
            delay = frames / ffmpeg.frame_rate(job.media) if frames else 0.0
            if frames:
                report(f"{name:6} audio delayed {frames} frame(s), {delay * 1000:+.1f} ms")
            ffmpeg.run(ffmpeg.encode_video_command(
                job.media, audio, job.output, audio_delay_s=delay
            ))
    # Encoding moves the true peak; the limiter's half-dB margin should absorb
    # it, and this says so when it has not.
    delivered = measure(job.output)
    if not meets_delivery(delivered.integrated_lufs, delivered.true_peak_db):
        report(
            f"{name:6} WARN  {job.output.name} is I {delivered.integrated_lufs:.1f} "
            f"LUFS  TP {delivered.true_peak_db:.1f} dB, outside "
            f"{TARGET_LUFS:g} LUFS / {TRUE_PEAK_LIMIT_DB:g} dBTP"
        )
    report(f"{name:6} wrote {job.output}")
    return job.output


def run(jobs: list[Job], parallel: int) -> int:
    """Prep every job; return how many failed.

    One at a time runs in this process. More each get their own: WhisperX and
    ffmpeg hold the GIL or a subprocess, so threads would gain nothing.
    """
    failed = 0
    if parallel <= 1 or len(jobs) <= 1:
        for job in jobs:
            failed += _report_failure(job, lambda job=job: prep_one(job))
        return failed

    context = multiprocessing.get_context("spawn")
    with ProcessPoolExecutor(max_workers=parallel, mp_context=context) as pool:
        futures = [(job, pool.submit(prep_one, job)) for job in jobs]
        for job, future in futures:
            failed += _report_failure(job, future.result)
    return failed


def _report_failure(job: Job, outcome) -> int:
    """Run `outcome`; a failure is reported against its file, not raised.

    Each file is independent, so one failing must not cost the others.
    """
    try:
        outcome()
    except Exception as error:  # every failure of one file, reported, not hidden
        report(f"{job.take.name:6} FAILED {job.media}: {error}")
        return 1
    return 0
