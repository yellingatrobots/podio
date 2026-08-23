"""Command-line entry point — the only place arguments are parsed.

Owns what the stages should not: ffmpeg normalization (with a temp file) and
constructing the real WhisperX transcriber.
"""

from __future__ import annotations

import argparse
import os
import sys
import textwrap
from pathlib import Path

from . import capture, censor, ffmpeg
from .bleep import render_file
from .clean import clean_all, clean_episode, report
from .config import scaffold
from .detect import transcribe_and_detect
from .transcribe import WhisperXTranscriber
from .wordlist import WordList

#: Defaults shipped with the tool, used unless an episode names its own.
#: Package data, not repo paths: podio is run from the episode directory, and
#: once installed there is no checkout above it.
DATA = Path(__file__).resolve().parent / "data"
WORDLIST = DATA / "wordlist.toml"
RIGS = DATA / "rigs"


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
    """Put a finished audio track over a source video, keeping the video as-is.

    The default is a QuickTime file whatever the source was, because that is
    the container the WAV survives in — see ffmpeg.PCM_CONTAINERS.
    """
    out = args.out or Path(args.video).with_name(f"{Path(args.video).stem}_muxed.mov")
    try:
        ffmpeg.mux(args.video, args.audio, out)
    except RuntimeError as error:
        report(f"error: {error}")
        return 1
    print(f"wrote {out}")
    return 0


def _cmd_devices(args) -> int:
    """List what this machine can record a bumper from.

    The numbers are podio's own, not the backend's, so that the same number
    means the same thing here as it does to `podio bumper --device`.
    """
    try:
        backend, devices = capture.discover()
    except ValueError as error:
        report(f"error: {error}")
        return 1

    report(f"capture devices ({backend.format}):")
    for device in devices:
        print(f"{'*' if device.is_default else ' '} {device.index:>2}  {device.name}")
    # The devices go to stdout so the list can be piped, the commentary to
    # stderr so it is not. Two streams only stay in order if this one is pushed
    # out before the next thing is said on the other.
    sys.stdout.flush()
    report("\npodio bumper records from the system's own microphone unless "
           "--device names one of these")
    return 0


def _cmd_bumper(args) -> int:
    """Record a bumper straight to a file, at the rate the pass works at.

    The overwrite check is the one podio does nowhere else: every other output
    can be rendered again from its inputs, and a recording cannot.
    """
    out = Path(args.out)
    if out.exists() and not args.force:
        report(f"error: {out} is already here; pass --force to record over it")
        return 1

    try:
        backend, devices = capture.discover()
        device = capture.resolve_device(args.device, devices, backend)
    except ValueError as error:
        report(f"error: {error}")
        return 1

    known = next(
        (d.name for d in devices if d.spec == device),
        device or "the system's own microphone",
    )
    report(f"recording {out} from {known} — press q to stop")
    try:
        ffmpeg.attach(capture.record_command(backend, device, out))
    except KeyboardInterrupt:
        # ffmpeg took the same interrupt and closed the file on its way out.
        pass

    if not out.exists():
        report("error: nothing was recorded")
        return 1
    print(f"wrote {out}")
    return 0


def _cmd_detect(args) -> int:
    wordlist = WordList.from_file(args.wordlist)
    transcriber = WhisperXTranscriber(
        model_size=args.model, device=args.device, language=args.language
    )

    # Straight at the file: WhisperX decodes what its model needs, so converting
    # here first only did the same work twice. See censor.detect_into.
    transcript, manifest = transcribe_and_detect(
        args.audio, transcriber, wordlist,
        inset=args.inset, min_confidence=args.min_confidence,
    )

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


#: What the whole pass does, and which command covers which part of it. Shown
#: under `podio --help`; each command repeats its own segment in more detail.
OVERVIEW = """\
the pass:

  takes ──▶ clean ─────────────────────────▶ prepped takes
                 └─▶ detect ──▶ manifests
                                └─▶ bleep ─▶ censored takes ──▶ NLE

  podio run       all of it, take by take
  podio clean     the first segment only — nothing is transcribed
  podio detect    one file  ──▶ one manifest (and its transcript)
  podio bleep     one manifest ──▶ one censored file

around it: 'devices' and 'bumper' record intros and outros, 'mux' puts a
finished track over a video, 'normalize' decodes anything to 16 kHz mono.
"""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="podio",
        description="Clean and censor the raw per-speaker takes of an episode.",
        epilog=OVERVIEW,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    def command(name: str, summary: str, chain: str):
        """Add a subcommand described by the chain of steps it runs."""
        # Blank lines go, indentation stays: a block that opens with its
        # diagram is indented, and that indent is part of the diagram.
        body = textwrap.dedent(chain).strip("\n")
        return sub.add_parser(
            name,
            help=summary,
            description=f"{summary}\n\n{body}",
            formatter_class=argparse.RawDescriptionHelpFormatter,
        )

    def add_clean_arguments(p):
        p.add_argument("takes", nargs="*", help="only these takes (default: all)")
        p.add_argument("-c", "--config", type=Path, default=Path("audio.toml"))
        p.add_argument("--rigs", type=Path, default=RIGS)
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

    p_run = command(
        "run", "clean then censor an episode — the whole pass",
        """
        For every take in audio.toml:

          take ──▶ chain (denoise, gate, EQ, compress) ──▶ gain match
               ──▶ NAME_prepped.wav
               ──▶ transcribe (WhisperX) ──▶ match the wordlist
               ──▶ NAME.manifest.json + NAME.transcript.json
               ──▶ splice the tone over each span ──▶ NAME_censored.wav

        Then audio.analysis.toml, recording what was measured.

        Where it stops early: --dry-run after measuring, --range after the
        chain (an audition is a slice, so its timings are not the take's),
        --review after the manifests, leaving 'podio bleep' to render them.
        A manifest edited by hand since detection wrote it stops the run
        rather than being overwritten; --redetect discards those edits.
        """,
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

    p_clean = command(
        "clean", "clean an episode's takes -> prepped takes",
        """
        For every take in audio.toml:

          take ──▶ chain (denoise, gate, EQ, compress) ──▶ gain match
               ──▶ NAME_prepped.wav

        Then audio.analysis.toml, recording what was measured.

        The first segment of 'podio run' on its own: nothing is transcribed
        and nothing is censored. Prepped takes are what 'podio detect' and
        'podio bleep' expect to be handed afterwards.
        """,
    )
    add_clean_arguments(p_clean)
    p_clean.set_defaults(func=_cmd_clean)

    p_devices = command(
        "devices", "list the microphones a bumper can be recorded from",
        """
        Records nothing. Numbers this machine's capture devices so that
        'podio bumper --device N' can name one of them.
        """,
    )
    p_devices.set_defaults(func=_cmd_devices)

    p_bumper = command(
        "bumper", "record a bumper from a microphone",
        """
          microphone ──▶ ffmpeg capture ──▶ mono 48 kHz 24-bit wav

        No chain and no gain match: a bumper is recorded deliberately in one
        go, and there is nothing to match it against. It comes out the same
        shape as a prepped take, so it drops onto the timeline beside one.
        Press q to stop. An existing file is kept unless --force.
        """,
    )
    p_bumper.add_argument("out", nargs="?", default="bumper.wav")
    p_bumper.add_argument(
        "--device",
        help="a number from 'podio devices', or a device name to pass straight "
             "to ffmpeg (default: the system's own choice, or device 0)",
    )
    p_bumper.add_argument(
        "--force", action="store_true", help="record over an existing file"
    )
    p_bumper.set_defaults(func=_cmd_bumper)

    p_norm = command(
        "normalize", "decode audio to 16kHz mono wav",
        """
          audio ──▶ ffmpeg decode ──▶ 16 kHz mono wav

        Stands outside the pass. Detection hands audio to WhisperX undecoded,
        so nothing here needs this; it is for looking at a file by hand.
        """,
    )
    p_norm.add_argument("audio")
    p_norm.add_argument("--out", default="normalized.wav")
    p_norm.set_defaults(func=_cmd_normalize)

    p_man = command(
        "detect", "detect profanity -> censor manifest JSON",
        """
          audio ──▶ transcribe (WhisperX) ──▶ match the wordlist
                ──▶ OUT.json (the spans to bleep)
                ──▶ OUT.transcript.json (every word, with its timing)

        Renders no audio: review the manifest, then 'podio bleep' to splice
        the tone over the spans it lists. 'podio run' does this step for a
        whole episode, against the prepped takes.
        """,
    )
    p_man.add_argument("audio")
    p_man.add_argument("--out", default="manifest.json")
    add_detect_arguments(p_man, wordlist_default=WORDLIST)
    p_man.set_defaults(func=_cmd_detect)

    p_mux = command(
        "mux", "replace a video's audio with a finished track",
        """
          video + audio ──▶ remux, picture copied through ──▶ SOURCE_muxed.mov

        After the pass, not part of it: the picture is never touched and the
        audio is never mixed. Syncing and mixing happen in the NLE.
        """,
    )
    p_mux.add_argument("video", help="the source video (its picture is copied through)")
    p_mux.add_argument("audio", help="the audio to put over it, e.g. a censored wav")
    p_mux.add_argument(
        "--out", default=None,
        help="output file (default: SOURCE_muxed.mov; .mov/.mkv keep the wav "
             "as it is, anything else re-encodes it to AAC)",
    )
    p_mux.set_defaults(func=_cmd_mux)

    p_bleep = command(
        "bleep", "render censored audio from a manifest",
        """
          audio + manifest ──▶ splice the tone over each span ──▶ censored wav

        The last step of 'podio run', on its own — this is how a manifest
        that was edited by hand gets rendered. Nothing is transcribed and no
        spans are detected: what the manifest lists is what gets bleeped.
        """,
    )
    p_bleep.add_argument("audio")
    p_bleep.add_argument("manifest")
    p_bleep.add_argument(
        "--out", default="censored.wav",
        help=f"output file (default: censored.wav). .wav and "
             f"{'/'.join(sorted(ffmpeg.PCM_CONTAINERS))} keep 24-bit PCM; "
             f"anything else has to encode the audio to AAC",
    )
    p_bleep.add_argument("--freq", type=float, default=1000.0)
    p_bleep.set_defaults(func=_cmd_bleep)

    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
