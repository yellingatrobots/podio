"""Command-line entry point.

Owns the two things the pure pipeline should not: ffmpeg normalization (with a
temp file) and constructing the real WhisperX transcriber.
"""

from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

from .audio import normalize_audio
from .pipeline import transcribe_and_detect
from .transcribe import WhisperXTranscriber
from .wordlist import WordList


def _cmd_normalize(args) -> int:
    normalize_audio(args.audio, args.out)
    print(f"wrote {args.out}")
    return 0


def _cmd_manifest(args) -> int:
    wordlist = WordList.from_file(args.wordlist)
    transcriber = WhisperXTranscriber(
        model_size=args.model, device=args.device, language=args.language
    )

    normalized = str(Path(tempfile.mkdtemp()) / "normalized.wav")
    normalize_audio(args.audio, normalized)

    transcript, manifest = transcribe_and_detect(
        normalized, transcriber, wordlist, inset=args.inset
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
    parser = argparse.ArgumentParser(prog="bleep", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p_norm = sub.add_parser("normalize", help="decode audio to 16kHz mono wav")
    p_norm.add_argument("audio")
    p_norm.add_argument("--out", default="normalized.wav")
    p_norm.set_defaults(func=_cmd_normalize)

    p_man = sub.add_parser("manifest", help="detect profanity -> censor manifest JSON")
    p_man.add_argument("audio")
    p_man.add_argument("--out", default="manifest.json")
    p_man.add_argument("--wordlist", default="config/wordlist.yaml")
    p_man.add_argument(
        "--inset", type=float, default=0.03,
        help="seconds to shrink each span edge inward (default 0.03)",
    )
    p_man.add_argument("--model", default="large-v3")
    p_man.add_argument("--device", default="cpu")
    p_man.add_argument("--language", default="en")
    p_man.set_defaults(func=_cmd_manifest)

    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
