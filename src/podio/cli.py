"""Command-line entry point — the only place arguments are parsed, and where
the real WhisperX transcriber is constructed.
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
import textwrap
from pathlib import Path

from . import __version__, capture, ffmpeg, prep
from .bleep import render_file
from .clean import measure_chain, process, report
from .config import EPISODE_CONFIG, episode_template, find_takes, load_take
from .detect import transcribe_and_detect
from .transcribe import WhisperXTranscriber
from .wordlist import WordList

#: Defaults shipped with the tool, used unless an episode names its own.
#: Package data, not repo paths: podio is run from the episode directory, and
#: once installed there is no checkout above it.
DATA = Path(__file__).resolve().parent / "data"
WORDLIST = DATA / "wordlist.toml"
RIGS = DATA / "rigs"


def _cmd_prep(args) -> int:
    """Prep every file given: validated together, then run independently."""
    try:
        jobs = prep.plan(
            args.files,
            rigs=args.rigs,
            rig=args.rig,
            bleep=not args.no_bleep,
            wordlist=args.wordlist,
            default_wordlist=WORDLIST,
            model=args.model,
            rnnoise_models=args.models,
            keep_temp=args.keep_temp,
        )
    except ValueError as error:
        report(f"error: {error}")
        return 1

    failed = prep.run(jobs, args.jobs or len(jobs))
    if failed:
        report(f"error: {failed} of {len(jobs)} file(s) failed")
        return 1
    return 0


def _cmd_init(args) -> int:
    """Write an audio.toml beside the takes, every setting at its default."""
    files = [Path(f) for f in args.files] or find_takes(Path.cwd())
    if not files:
        report(f"error: no takes in {Path.cwd()}; name the files to configure")
        return 1
    directories = {f.parent.resolve() for f in files}
    if len(directories) > 1:
        report("error: an audio.toml configures one directory; the files are in "
               + ", ".join(str(d) for d in sorted(directories)))
        return 1
    config = files[0].parent / EPISODE_CONFIG
    if config.exists() and not args.force:
        report(f"error: {config} exists; --force writes over it")
        return 1
    config.write_text(episode_template(files, args.rigs))
    print(f"wrote {config} ({', '.join(f.stem for f in files)})")
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
    """Record a bumper straight to a file, at the rate prep writes.

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


def _cmd_clean(args) -> int:
    """Clean and level each file on its own, with no detection or bleep."""
    try:
        takes = [load_take(Path(f), args.rigs, args.rig) for f in args.files]
        for take in takes:
            if args.dry_run:
                _, chain = measure_chain(take, args.models)
                report(f"{take.name:6} chain {chain}")
                continue
            out = Path(take.source).with_name(f"{take.name}_cleaned.wav")
            with tempfile.TemporaryDirectory(prefix="podio_") as tmp:
                process(take, args.models, Path(tmp), out)
            print(f"wrote {out}")
    except (ValueError, RuntimeError) as error:
        report(f"error: {error}")
        return 1
    return 0


def _cmd_detect(args) -> int:
    wordlist = WordList.from_file(args.wordlist)
    transcriber = WhisperXTranscriber(
        model_size=args.model, device=args.asr_device, language=args.language
    )

    # Straight at the file: WhisperX decodes what its model needs, so converting
    # here first only did the same work twice. See censor.detect_into.
    transcript, manifest = transcribe_and_detect(
        args.audio, transcriber, wordlist,
        inset=args.inset, min_confidence=args.min_confidence,
    )

    manifest_path = Path(args.out)
    take_name = manifest_path.stem.removesuffix("_manifest")
    transcript_path = manifest_path.with_name(f"{take_name}_transcript.json")
    manifest_path.write_text(manifest.to_json())
    transcript_path.write_text(transcript.to_json())

    print(
        f"wrote {manifest_path} ({len(manifest.spans)} span(s) to bleep) "
        f"and {transcript_path} ({len(transcript.words)} words)"
    )
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


def _cmd_normalize(args) -> int:
    ffmpeg.normalize(args.audio, args.out)
    print(f"wrote {args.out}")
    return 0


#: The top-level help, written out because argparse lists subcommands flat.
OVERVIEW = """\
Make podcast recordings ready for production.

  podio prep FILE...   NAME.mp4 or NAME.wav ──▶ clean ──▶ -16 LUFS ──▶ bleep
                       ──▶ NAME_prepped.mp4 or NAME_prepped.wav
  podio init [FILE...] write audio.toml: every setting, at its default
  podio devices        list the microphones a bumper can be recorded from
  podio bumper [OUT]   record an intro or outro straight to a 48 kHz wav

  podio debug STEP     run one step of prep on its own

'podio COMMAND --help' shows a command's steps and options.
"""

DEBUG_OVERVIEW = """\
debug: run one step of prep on its own, to find what went wrong.

  podio debug clean FILE...       the chain and -16 LUFS ──▶ NAME_cleaned.wav
                                  (--dry-run: print the noise floor and the
                                  resolved chain, write nothing)
  podio debug detect AUDIO        transcribe, match the wordlist
                                  ──▶ manifest.json + NAME_transcript.json
  podio debug bleep AUDIO MANIFEST  tone over each span ──▶ censored.wav
  podio debug mux VIDEO AUDIO     audio over the picture ──▶ VIDEO_muxed.mov
  podio debug normalize AUDIO     16 kHz mono, as WhisperX hears it
"""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="podio",
        # Spelled out because the command list is suppressed, and with it
        # argparse's own mention of COMMAND.
        usage="podio [-h] [--version] COMMAND ...",
        description=OVERVIEW,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--version", action="version", version=f"podio {__version__}"
    )
    sub = parser.add_subparsers(
        dest="command", required=True, metavar="COMMAND", help=argparse.SUPPRESS,
        prog="podio",
    )

    def command(name: str, description: str):
        """Add a subcommand. Its description opens with its one-line summary."""
        # Blank lines go, indentation stays: a block that opens with its
        # diagram is indented, and that indent is part of the diagram.
        body = textwrap.dedent(description).strip("\n")
        return sub.add_parser(
            name,
            description=body,
            formatter_class=argparse.RawDescriptionHelpFormatter,
        )

    def add_take_arguments(p):
        p.add_argument("--rigs", type=Path, default=RIGS,
                       help="directory of rig files (default: the rigs podio ships)")
        p.add_argument("--rig", default=None, metavar="NAME",
                       help="the rig for every FILE, over audio.toml's and the "
                            "one named after the file")
        p.add_argument("--rnnoise-models", dest="models", type=Path,
                       default=Path(os.environ.get("RNNOISE_MODELS", "")),
                       help="directory of .rnnn files for rnnoise "
                            "(default: $RNNOISE_MODELS)")

    def add_detect_arguments(group, *, wordlist_default, wordlist_help):
        group.add_argument("--wordlist", default=wordlist_default, help=wordlist_help)
        group.add_argument(
            "--model", default="base.en",
            help="WhisperX model (default base.en; large-v3 for higher accuracy)",
        )
        group.add_argument(
            "--asr-device", default="cpu",
            help="where WhisperX runs: cpu or cuda (default cpu)",
        )
        group.add_argument(
            "--language", default="en", help="the language spoken (default en)"
        )
        group.add_argument(
            "--min-confidence", type=float, default=0.0,
            help="drop words heard below this ASR confidence (default 0: keep all)",
        )
        group.add_argument(
            "--inset", type=float, default=0.03,
            help="seconds to shrink each span edge inward (default 0.03)",
        )

    p_prep = command(
        "prep",
        """
        make each FILE ready for production.

          NAME.mp4 or NAME.wav
            1  clean   the rig's chain, at 48 kHz
            2  level   -16 LUFS integrated, under -1 dBTP
            3  detect  transcribe (WhisperX), match the wordlist
            4  bleep   a tone over each word found
          ──▶ NAME_prepped.mp4 (picture copied, 192 kbps AAC)
              or NAME_prepped.wav (24-bit, 48 kHz)

        A NAME.wav beside NAME.mp4 is the audio; the mp4 then only gives the
        picture. The rig is --rig if given, else the one an audio.toml beside
        the file names in [takes.NAME] rig = "...", else the one named NAME.
        Every file is checked before any work starts; then they run in
        parallel, and one failing does not stop the others. Intermediates go
        to a temporary directory.
        """,
    )
    p_prep.add_argument("files", nargs="+", type=Path, metavar="FILE",
                        help="an .mp4 (or other video) or a .wav")
    p_prep.add_argument("--no-bleep", action="store_true",
                        help="skip steps 3 and 4: nothing is transcribed or bleeped")
    p_prep.add_argument("-j", "--jobs", type=int, default=None, metavar="N",
                        help="files to prep at once (default: all of them)")
    p_prep.add_argument("--keep-temp", type=Path, default=None, metavar="DIR",
                        help="keep the intermediates of each file in DIR/NAME")
    p_prep.add_argument("--model", default="base.en",
                        help="WhisperX model (default base.en; large-v3 for "
                             "higher accuracy)")
    p_prep.add_argument("--wordlist", type=Path, default=None,
                        help="wordlist to bleep (default: audio.toml's [censor] "
                             "wordlist, else the one podio ships)")
    add_take_arguments(p_prep)
    p_prep.set_defaults(func=_cmd_prep)

    p_init = command(
        "init",
        f"""
        write an {EPISODE_CONFIG} with every setting at its default.

          FILE... (default: the takes here) ──▶ {EPISODE_CONFIG} beside them

        Each take gets its rig, its audio delay and every stage of the rig,
        all commented out at the value the take gets without the file. A
        take with no rig of its name gets the rigs to choose from. Files podio
        wrote (NAME_prepped and the like) are not takes. An existing
        {EPISODE_CONFIG} is kept unless --force.
        """,
    )
    p_init.add_argument("files", nargs="*", type=Path, metavar="FILE",
                        help="the takes to configure (default: every take in "
                             "this directory)")
    p_init.add_argument("--rigs", type=Path, default=RIGS,
                        help="directory of rig files (default: the rigs podio ships)")
    p_init.add_argument("--force", action="store_true",
                        help=f"write over an existing {EPISODE_CONFIG}")
    p_init.set_defaults(func=_cmd_init)

    p_devices = command(
        "devices",
        """
        list the microphones a bumper can be recorded from.

        Records nothing. Numbers this machine's capture devices so that
        'podio bumper --device N' can name one. The numbers shift when a
        device connects; the name printed beside each one does not.
        """,
    )
    p_devices.set_defaults(func=_cmd_devices)

    p_bumper = command(
        "bumper",
        """
        record an intro, outro or transition.

          microphone ──▶ ffmpeg capture ──▶ OUT, mono 48 kHz 24-bit

        Captured through OpenAL; on Linux, pulse or alsa if OpenAL finds
        nothing.

        Recorded raw, at the rate prep writes. To bring it to the takes'
        loudness: 'podio prep OUT --no-bleep'. Press q to stop. An existing OUT is kept unless --force.
        """,
    )
    p_bumper.add_argument(
        "out", nargs="?", default="bumper.wav",
        help="the file to record to (default: bumper.wav)",
    )
    p_bumper.add_argument(
        "--device",
        help="a number from 'podio devices', or a device name to pass straight "
             "to ffmpeg (default: the system's own choice)",
    )
    p_bumper.add_argument(
        "--force", action="store_true", help="record over an existing file"
    )
    p_bumper.set_defaults(func=_cmd_bumper)

    p_debug = command("debug", DEBUG_OVERVIEW)
    # STEP is suppressed from argparse's list, so it is named here instead.
    p_debug.usage = "podio debug [-h] STEP ..."
    sub = p_debug.add_subparsers(
        dest="step", required=True, metavar="STEP", help=argparse.SUPPRESS,
        prog="podio debug",
    )

    p_clean = command(
        "clean",
        """
        debug: clean and level each FILE, with no detection or bleep.

          1  measure  the noise floor: the 10th percentile of 1-second
                      windows, so "floor+N" values in the chain can resolve
          2  chain    the rig's enabled stages, with audio.toml's overrides,
                      at 48 kHz
          3  level    gain and a true-peak limiter to -16 LUFS under -1 dBTP
          ──▶ NAME_cleaned.wav beside FILE, 24-bit, 48 kHz

        The rig and audio.toml are found as 'podio prep' finds them.
        """,
    )
    p_clean.add_argument("files", nargs="+", type=Path, metavar="FILE")
    p_clean.add_argument("--dry-run", action="store_true",
                         help="print the noise floor and resolved chain; write nothing")
    add_take_arguments(p_clean)
    p_clean.set_defaults(func=_cmd_clean)

    p_man = command(
        "detect",
        """
        debug: find the words to bleep in one file.

          1  transcribe  WhisperX: every word, with its timing (the first run
                         downloads the model)
          2  match       whole words and phrases from the wordlist, never
                         substrings; the allowlist is never matched
          3  adjust      drop spans under --min-confidence, shrink each edge
                         by --inset, merge what still overlaps
          ──▶ OUT (default manifest.json): the spans to bleep
          ──▶ NAME_transcript.json beside it, where NAME is OUT's name
              without _manifest: every word heard

        Renders no audio. next: read or edit the manifest, then
        'podio debug bleep'.
        """,
    )
    p_man.add_argument("audio", help="the audio to transcribe, e.g. a cleaned take")
    p_man.add_argument(
        "--out", default="manifest.json",
        help="the manifest to write (default: manifest.json)",
    )
    add_detect_arguments(
        p_man.add_argument_group("detection"),
        wordlist_default=WORDLIST, wordlist_help="wordlist to censor against "
        "(default: the one podio ships)",
    )
    p_man.set_defaults(func=_cmd_detect)

    p_bleep = command(
        "bleep",
        """
        debug: put the tone over every span of one file.

          1  decode   AUDIO at its own rate, as mono
          2  splice   a sine tone (1 kHz, --freq) at -19 dBFS RMS over each
                      span MANIFEST lists; every other sample is untouched
          ──▶ OUT (default censored.wav)

        OUT's extension picks the output: .wav is 24-bit audio; .mov or .mkv
        put the 24-bit audio back over AUDIO's video; anything else does the
        same but has to encode the audio to AAC.

        Nothing is transcribed: what the manifest lists is what gets bleeped,
        which is how a manifest edited by hand is rendered.
        """,
    )
    p_bleep.add_argument("audio", help="the audio to censor, e.g. a cleaned take")
    p_bleep.add_argument("manifest", help="the spans to bleep, from 'podio debug detect'")
    p_bleep.add_argument(
        "--out", default="censored.wav",
        help=f"output file (default: censored.wav). .wav and "
             f"{'/'.join(sorted(ffmpeg.PCM_CONTAINERS))} keep 24-bit PCM; "
             f"anything else has to encode the audio to AAC",
    )
    p_bleep.add_argument(
        "--freq", type=float, default=1000.0,
        help="the tone's frequency in Hz (default 1000)",
    )
    p_bleep.set_defaults(func=_cmd_bleep)

    p_mux = command(
        "mux",
        """
        debug: put a finished track over a video.

          VIDEO + AUDIO ──▶ picture copied, audio replaced ──▶ OUT

        OUT defaults to VIDEO_muxed.mov. .mov and .mkv copy the wav in as
        it is; anything else re-encodes it to AAC. Nothing is synced or
        mixed.
        """,
    )
    p_mux.add_argument("video", help="the source video (its picture is copied through)")
    p_mux.add_argument("audio", help="the audio to put over it, e.g. a censored take")
    p_mux.add_argument(
        "--out", default=None,
        help="output file (default: VIDEO_muxed.mov; .mov/.mkv keep the wav "
             "as it is, anything else re-encodes it to AAC)",
    )
    p_mux.set_defaults(func=_cmd_mux)

    p_norm = command(
        "normalize",
        """
        debug: decode any audio to 16 kHz mono wav.

          AUDIO ──▶ ffmpeg decode ──▶ OUT, 16 kHz mono

        Prep does not need this: detection hands audio to WhisperX
        undecoded. It is for listening to a file the way the ASR hears it.
        """,
    )
    p_norm.add_argument("audio", help="any file ffmpeg can decode")
    p_norm.add_argument(
        "--out", default="normalized.wav",
        help="the wav to write (default: normalized.wav)",
    )
    p_norm.set_defaults(func=_cmd_normalize)

    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
