"""Command-line entry point — the only place arguments are parsed.

Owns what the stages should not: ffmpeg normalization (with a temp file) and
constructing the real WhisperX transcriber.
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
from pathlib import Path

from . import ffmpeg
from .bleep import DEFAULT_AMPLITUDE, render_file
from .clean import ROOT, clean_episode
from .detect import transcribe_and_detect
from .transcribe import WhisperXTranscriber
from .wordlist import WordList


def _cmd_normalize(args) -> int:
    ffmpeg.normalize(args.audio, args.out)
    print(f"wrote {args.out}")
    return 0


def _cmd_bleep(args) -> int:
    render_file(
        args.audio, args.manifest, args.out,
        freq=args.freq, amplitude=args.amplitude,
    )
    print(f"wrote {args.out}")
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="podio", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p_clean = sub.add_parser("clean", help="clean an episode's takes -> prepped takes")
    p_clean.add_argument(
        "takes", nargs="*", help="only process these takes (default: all)"
    )
    p_clean.add_argument("-c", "--config", type=Path, default=Path("audio.toml"))
    p_clean.add_argument("--rigs", type=Path, default=ROOT / "rigs")
    p_clean.add_argument(
        "--range",
        dest="audition",
        help="render only this slice, as START+SECONDS (e.g. 21:30+45)",
    )
    p_clean.add_argument(
        "--models",
        type=Path,
        default=Path(os.environ.get("RNNOISE_MODELS", "")),
        help="directory of .rnnn files (default: $RNNOISE_MODELS)",
    )
    p_clean.add_argument(
        "--dry-run",
        action="store_true",
        help="measure and print the resolved chain, but render nothing",
    )
    p_clean.set_defaults(func=clean_episode)

    p_norm = sub.add_parser("normalize", help="decode audio to 16kHz mono wav")
    p_norm.add_argument("audio")
    p_norm.add_argument("--out", default="normalized.wav")
    p_norm.set_defaults(func=_cmd_normalize)

    p_man = sub.add_parser("detect", help="detect profanity -> censor manifest JSON")
    p_man.add_argument("audio")
    p_man.add_argument("--out", default="manifest.json")
    p_man.add_argument("--wordlist", default="config/wordlist.toml")
    p_man.add_argument(
        "--inset", type=float, default=0.03,
        help="seconds to shrink each span edge inward (default 0.03)",
    )
    p_man.add_argument(
        "--min-confidence", type=float, default=0.0,
        help="drop detections below this ASR confidence (default 0: keep all)",
    )
    p_man.add_argument(
        "--model", default="base.en",
        help="WhisperX model (default base.en; large-v3 for higher accuracy)",
    )
    p_man.add_argument("--device", default="cpu")
    p_man.add_argument("--language", default="en")
    p_man.set_defaults(func=_cmd_detect)

    p_bleep = sub.add_parser("bleep", help="render censored audio from a manifest")
    p_bleep.add_argument("audio")
    p_bleep.add_argument("manifest")
    p_bleep.add_argument("--out", default="censored.wav")
    p_bleep.add_argument("--freq", type=float, default=1000.0)
    p_bleep.add_argument(
        "--amplitude", type=int, default=DEFAULT_AMPLITUDE,
        help="tone amplitude in 32-bit sample units (default: full-scale/2.7)",
    )
    p_bleep.set_defaults(func=_cmd_bleep)

    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
