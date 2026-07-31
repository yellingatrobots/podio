"""Command-line entry point — the only place arguments are parsed.

Owns what the stages should not: ffmpeg normalization (with a temp file) and
constructing the real WhisperX transcriber.
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
import textwrap
from pathlib import Path

from . import censor, ffmpeg
from .bleep import render_file
from .clean import ROOT, clean_all, clean_episode, report
from .config import scaffold
from .detect import transcribe_and_detect
from .transcribe import WhisperXTranscriber
from .wordlist import WordList

#: The wordlist shipped with the tool, used unless an episode names its own.
#: An absolute path, because podio is run from the episode directory.
WORDLIST = ROOT / "config" / "wordlist.toml"


def _cmd_normalize(args) -> int:
    ffmpeg.normalize(args.audio, args.out)
    print(f"wrote {args.out}")
    return 0


def _cmd_bleep(args) -> int:
    render_file(
        args.audio, args.manifest, args.out,
        freq=args.freq,
    )
    print(f"wrote {args.out}")
    return 0


def _cmd_mux(args) -> int:
    """Put a finished audio track over a source video, keeping the video as-is."""
    out = args.out or Path(args.video).with_name(
        f"{Path(args.video).stem}_muxed{Path(args.video).suffix}"
    )
    try:
        ffmpeg.mux(args.video, args.audio, out)
    except RuntimeError as error:
        report(f"error: {error}")
        return 1
    print(f"wrote {out}")
    return 0


def _cmd_detect(args) -> int:
    wordlist = WordList.from_file(args.wordlist)
    transcriber = WhisperXTranscriber(
        model_size=args.model, device=args.device, language=args.language
    )

    with tempfile.TemporaryDirectory() as tmp:
        normalized = str(Path(tmp) / "normalized.wav")
        ffmpeg.normalize(args.audio, normalized)
        transcript, manifest = transcribe_and_detect(
            normalized, transcriber, wordlist,
            inset=args.inset, min_confidence=args.min_confidence,
        )
    # Report against the original file, not the temp normalized copy.
    transcript.audio_path = manifest.audio_path = args.audio

    manifest_path = Path(args.out)
    transcript_path = manifest_path.with_name(manifest_path.stem + ".transcript.json")
    manifest_path.write_text(manifest.to_json())
    transcript_path.write_text(transcript.to_json())

    print(
        f"wrote {manifest_path} ({len(manifest.spans)} span(s) to bleep) "
        f"and {transcript_path} ({len(transcript.words)} words)"
    )
    return 0


def _confirm_stub(proposed: str) -> bool:
    report(f"There is no {Path('audio.toml')} here. podio can write this:\n")
    report(textwrap.indent(proposed.rstrip(), "    "))
    try:
        return input("\nwrite it? [y/N] ").strip().lower() in {"y", "yes"}
    except EOFError:
        return False


def _offer_stub(args) -> None:
    """Offer to scaffold a missing audio.toml, when someone is there to ask.

    Declining, or not being asked at all, falls through to the ordinary missing
    config error — this only ever adds a way forward, never a new failure.
    """
    if args.config.exists() or not sys.stdin.isatty():
        return
    try:
        if scaffold(args.config, args.rigs, ask=_confirm_stub):
            report(f"wrote {args.config}")
    except ValueError as error:
        report(f"error: {error}")


def _cmd_clean(args) -> int:
    _offer_stub(args)
    return clean_episode(args)


def _cmd_run(args) -> int:
    """Clean every take, then censor the ones that asked for it."""
    _offer_stub(args)
    try:
        episode, results = clean_all(args)
    except (ValueError, RuntimeError) as error:
        report(f"error: {error}")
        return 1

    if args.dry_run:
        return 0
    if args.audition:
        # An audition is a slice, so its manifest would be timed against the
        # slice rather than the take. Auditioning checks the chain, not the words.
        report("       audition: chain only, nothing censored")
        return 0

    wanted = [r for r in results if r.take.censor.enabled]
    if not wanted:
        report("       censoring is off for every take")
        return 0

    episode_dir = args.config.parent
    for result in wanted:
        name = result.take.name
        manifest = censor.manifest_path(episode_dir, name)
        transcript = censor.transcript_path(episode_dir, name)

        if censor.is_hand_edited(manifest, transcript) and not args.redetect:
            report(
                f"{name:6} STOP  {manifest.name} has been edited since detection "
                f"wrote it. Re-running would discard those edits. Render them with "
                f"'podio bleep {result.output.name} {manifest.name}', or pass "
                f"--redetect to throw them away and detect again."
            )
            return 1

        try:
            # An explicit flag wins, then the episode's choice, then the default.
            wordlist = WordList.from_file(
                args.wordlist or result.take.censor.wordlist or WORDLIST
            )
            transcriber = WhisperXTranscriber(
                model_size=args.model, device=args.device, language=args.language
            )
            manifest, spans = censor.detect_into(
                result.output, episode_dir, name, wordlist, transcriber,
                inset=args.inset, min_confidence=args.min_confidence,
            )
            report(f"{name:6} detected {spans} span(s) -> {manifest.name}")

            if args.review:
                continue
            out = censor.splice(result.output, manifest, episode_dir, name)
            report(f"{name:6} wrote {out.name}")
        except (ValueError, RuntimeError) as error:
            report(f"error: {error}")
            return 1

    if args.review:
        report("       review the manifests, then 'podio bleep' to render")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="podio", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    def add_clean_arguments(p):
        p.add_argument("takes", nargs="*", help="only these takes (default: all)")
        p.add_argument("-c", "--config", type=Path, default=Path("audio.toml"))
        p.add_argument("--rigs", type=Path, default=ROOT / "rigs")
        p.add_argument(
            "--range",
            dest="audition",
            help="render only this slice, as START+SECONDS (e.g. 21:30+45)",
        )
        p.add_argument(
            "--models",
            type=Path,
            default=Path(os.environ.get("RNNOISE_MODELS", "")),
            help="directory of .rnnn files (default: $RNNOISE_MODELS)",
        )
        p.add_argument(
            "--dry-run",
            action="store_true",
            help="measure and print the resolved chain, but render nothing",
        )

    def add_detect_arguments(p, *, wordlist_default):
        p.add_argument("--wordlist", default=wordlist_default)
        p.add_argument(
            "--inset", type=float, default=0.03,
            help="seconds to shrink each span edge inward (default 0.03)",
        )
        p.add_argument(
            "--min-confidence", type=float, default=0.0,
            help="drop detections below this ASR confidence (default 0: keep all)",
        )
        p.add_argument(
            "--model", default="base.en",
            help="WhisperX model (default base.en; large-v3 for higher accuracy)",
        )
        p.add_argument("--device", default="cpu")
        p.add_argument("--language", default="en")

    p_run = sub.add_parser(
        "run", help="clean then censor an episode — the whole pass"
    )
    add_clean_arguments(p_run)
    add_detect_arguments(p_run, wordlist_default=None)
    p_run.add_argument(
        "--review",
        action="store_true",
        help="stop after detection so the manifests can be read before splicing",
    )
    p_run.add_argument(
        "--redetect",
        action="store_true",
        help="re-detect even where a manifest has been edited by hand, losing those edits",
    )
    p_run.set_defaults(func=_cmd_run)

    p_clean = sub.add_parser("clean", help="clean an episode's takes -> prepped takes")
    add_clean_arguments(p_clean)
    p_clean.set_defaults(func=_cmd_clean)

    p_norm = sub.add_parser("normalize", help="decode audio to 16kHz mono wav")
    p_norm.add_argument("audio")
    p_norm.add_argument("--out", default="normalized.wav")
    p_norm.set_defaults(func=_cmd_normalize)

    p_man = sub.add_parser("detect", help="detect profanity -> censor manifest JSON")
    p_man.add_argument("audio")
    p_man.add_argument("--out", default="manifest.json")
    add_detect_arguments(p_man, wordlist_default=WORDLIST)
    p_man.set_defaults(func=_cmd_detect)

    p_mux = sub.add_parser(
        "mux", help="replace a video's audio with a finished track"
    )
    p_mux.add_argument("video", help="the source video (its picture is copied through)")
    p_mux.add_argument("audio", help="the audio to put over it, e.g. a censored wav")
    p_mux.add_argument(
        "--out", default=None, help="output file (default: SOURCE_muxed.EXT)"
    )
    p_mux.set_defaults(func=_cmd_mux)

    p_bleep = sub.add_parser("bleep", help="render censored audio from a manifest")
    p_bleep.add_argument("audio")
    p_bleep.add_argument("manifest")
    p_bleep.add_argument("--out", default="censored.wav")
    p_bleep.add_argument("--freq", type=float, default=1000.0)
    p_bleep.set_defaults(func=_cmd_bleep)

    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
