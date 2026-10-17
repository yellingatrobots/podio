"""Command-line entry point — the only place arguments are parsed, and where
the real WhisperX transcriber is constructed.
"""

from __future__ import annotations

import argparse
import os
import sys
import textwrap
from pathlib import Path

from . import __version__, capture, censor, config, ffmpeg, master
from .bleep import render_file
from .clean import Result, clean_all, clean_episode, report, select_takes
from .config import scaffold
from .detect import transcribe_and_detect
from .levels import TARGET_LUFS, TRUE_PEAK_LIMIT_DB, meets_delivery
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


def _cmd_master(args) -> int:
    """Bring the NLE's mixdown to delivery loudness, for video and the feed."""
    video = Path(args.video)
    stem = Path(args.out) if args.out else master.default_stem(video)
    try:
        result = master.master(video, stem)
    except (ValueError, RuntimeError) as error:
        report(f"error: {error}")
        return 1

    source = result.source
    report(
        f"mixdown  I {source.integrated_lufs:6.1f} LUFS  TP {source.true_peak_db:5.1f} dB"
        f"  gain {result.gain_db:+.1f} dB"
    )
    for out, loudness in result.delivered.items():
        report(
            f"{out.suffix[1:]:8} I {loudness.integrated_lufs:6.1f} LUFS"
            f"  TP {loudness.true_peak_db:5.1f} dB"
        )
        if not meets_delivery(loudness.integrated_lufs, loudness.true_peak_db):
            report(
                f"WARN     {out.name} misses {TARGET_LUFS:g} LUFS / "
                f"{TRUE_PEAK_LIMIT_DB:g} dBTP"
            )
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
    take_name = manifest_path.stem.removesuffix("_manifest")
    transcript_path = manifest_path.with_name(f"{take_name}_transcript.json")
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


def _run_episode(args, output_dir: Path) -> tuple[int, list[Result]]:
    """Clean and censor the selected takes into `output_dir`."""
    _offer_stub(args)
    try:
        _, results = clean_all(args, output_dir)
    except (ValueError, RuntimeError) as error:
        report(f"error: {error}")
        return 1, []

    if args.dry_run:
        return 0, results
    if args.audition:
        # An audition is a slice, so its manifest would be timed against the
        # slice rather than the take. Auditioning checks the chain, not the words.
        report("       audition: chain only, nothing censored")
        return 0, results

    wanted = [r for r in results if r.take.censor.enabled]
    if not wanted:
        report("       censoring is off for every take")
        return 0, results

    for result in wanted:
        name = result.take.name
        manifest = censor.manifest_path(output_dir, name)
        transcript = censor.transcript_path(output_dir, name)

        if censor.is_hand_edited(manifest, transcript) and not args.redetect:
            report(
                f"{name:6} STOP  {manifest.name} has been edited since detection "
                f"wrote it. Re-running would discard those edits. Render them with "
                f"'podio bleep {result.output} {manifest}', or pass "
                f"--redetect to throw them away and detect again."
            )
            return 1, []

        try:
            # An explicit flag wins, then the episode's choice, then the default.
            wordlist = WordList.from_file(
                args.wordlist or result.take.censor.wordlist or WORDLIST
            )
            transcriber = WhisperXTranscriber(
                model_size=args.model, device=args.device, language=args.language
            )
            manifest, spans = censor.detect_into(
                result.output, output_dir, name, wordlist, transcriber,
                inset=args.inset, min_confidence=args.min_confidence,
            )
            report(f"{name:6} detected {spans} span(s) -> {manifest.name}")

            if args.review:
                continue
            out = censor.splice(result.output, manifest, output_dir, name)
            report(f"{name:6} wrote {out.name}")
        except (ValueError, RuntimeError) as error:
            report(f"error: {error}")
            return 1, []

    if args.review:
        report("       review the manifests, then 'podio bleep' to render")
    return 0, results


def _cmd_run(args) -> int:
    """Clean every take, then censor the ones that asked for it."""
    status, _ = _run_episode(args, args.config.parent)
    return status


def _cmd_finish(args) -> int:
    """Clean and censor an episode, then mux each take's matching video."""
    _offer_stub(args)
    try:
        episode = config.load_episode(args.config, args.rigs)
        takes = select_takes(episode.takes, args.takes, args.config)
        videos = {
            take.name: args.config.parent / f"{take.name}.mp4" for take in takes
        }
        missing = [path for path in videos.values() if not path.exists()]
        if missing:
            raise ValueError(f"no matching video at {missing[0]}")
    except ValueError as error:
        report(f"error: {error}")
        return 1

    output_dir = args.artifacts
    if not output_dir.is_absolute():
        output_dir = args.config.parent / output_dir
    status, results = _run_episode(args, output_dir)
    if status:
        return status

    try:
        for result in results:
            name = result.take.name
            audio = (
                censor.censored_path(output_dir, name)
                if result.take.censor.enabled
                else result.output
            )
            out = args.config.parent / f"{name}_muxed.mov"
            ffmpeg.mux(videos[name], audio, out)
            report(f"{name:6} wrote {out.name}")
    except RuntimeError as error:
        report(f"error: {error}")
        return 1
    return 0


#: The top-level help. argparse lists subcommands flat and in no useful order,
#: so the list is written out here — the pass in step order, then what stands
#: outside it — and argparse's own is suppressed.
OVERVIEW = """\
Clean and censor the raw per-speaker takes of an episode, then master the
NLE's mixdown.

the pass, in order — run from the episode directory, takes from audio.toml:

  1  clean    each take ──▶ chain ──▶ gain match ──▶ NAME_prepped.wav
  2  detect   prepped take ──▶ transcribe ──▶ wordlist ──▶ NAME_manifest.json
  3  bleep    prepped take + manifest ──▶ tone over spans ──▶ NAME_censored.wav
  4  mux      NAME.mp4 + censored take ──▶ NAME_muxed.mov
              ··· sync, edit and mix in the NLE; export the mixdown ···
  5  master   mixdown.mp4 ──▶ -16 LUFS / -1 dBTP ──▶ STEM.mp4 + STEM.mp3

commands that run the pass:

  podio run       steps 1-3, every take
  podio finish    steps 1-4, every take
  podio clean     step 1, every take
  podio detect    step 2, one file
  podio bleep     step 3, one file
  podio mux       step 4, one file
  podio master    step 5, the NLE's mixdown

standalone, outside the pass:

  podio devices     list the microphones a bumper can be recorded from
  podio bumper      record an intro or outro straight to a 48 kHz wav
  podio normalize   decode any audio to 16 kHz mono wav, to inspect it

'podio COMMAND --help' shows a command's steps and options.
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
        dest="command", required=True, metavar="COMMAND", help=argparse.SUPPRESS
    )

    def command(name: str, description: str):
        """Add a subcommand. Its description opens with where it sits in the
        pass, which is also its one-line summary."""
        # Blank lines go, indentation stays: a block that opens with its
        # diagram is indented, and that indent is part of the diagram.
        body = textwrap.dedent(description).strip("\n")
        return sub.add_parser(
            name,
            description=body,
            formatter_class=argparse.RawDescriptionHelpFormatter,
        )

    def add_episode_arguments(p):
        """The takes and where the episode is; returns the group for more."""
        p.add_argument("takes", nargs="*", help="only these takes (default: all)")
        episode = p.add_argument_group("episode")
        episode.add_argument(
            "-c", "--config", type=Path, default=Path("audio.toml"),
            help="the episode's config (default: audio.toml)",
        )
        episode.add_argument(
            "--rigs", type=Path, default=RIGS,
            help="directory of rig files (default: the rigs podio ships)",
        )
        return episode

    def add_clean_arguments(p, *, partial=True):
        clean = p.add_argument_group("step 1, clean")
        clean.add_argument(
            "--models",
            type=Path,
            default=Path(os.environ.get("RNNOISE_MODELS", "")),
            help="directory of .rnnn files for rnnoise (default: $RNNOISE_MODELS)",
        )
        if partial:
            clean.add_argument(
                "--dry-run",
                action="store_true",
                help="measure and print each resolved chain, render nothing",
            )
            clean.add_argument(
                "--range",
                dest="audition",
                metavar="START+SECONDS",
                help="render only this slice (e.g. 21:30+45) to "
                     "NAME_audition.wav, and stop",
            )
        else:
            p.set_defaults(audition=None, dry_run=False)

    def add_detect_arguments(group, *, wordlist_default, wordlist_help):
        group.add_argument("--wordlist", default=wordlist_default, help=wordlist_help)
        group.add_argument(
            "--model", default="base.en",
            help="WhisperX model (default base.en; large-v3 for higher accuracy)",
        )
        group.add_argument(
            "--device", default="cpu",
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

    episode_wordlist = (
        "wordlist to censor against (default: the episode's [censor] "
        "wordlist, else the one podio ships)"
    )

    def add_redetect(group):
        group.add_argument(
            "--redetect",
            action="store_true",
            help="detect again over manifests edited by hand, losing the edits",
        )

    p_run = command(
        "run",
        """
        steps 1-3 of the pass: clean, detect and bleep every take.

        For every take in audio.toml, or only the TAKES named:

          1  clean    measure ──▶ chain ──▶ gain match ──▶ NAME_prepped.wav
          2  detect   transcribe (WhisperX) ──▶ match the wordlist
                      ──▶ NAME_manifest.json + NAME_transcript.json
          3  bleep    tone over each span ──▶ NAME_censored.wav

        Then audio_analysis.toml, recording what step 1 measured. A take with
        censoring off in audio.toml stops after step 1.

        Stopping early:
          --dry-run   during step 1, after measuring; writes nothing
          --range     after step 1, as NAME_audition.wav (a slice's timings
                      are not the take's, so it is never censored)
          --review    after step 2, so the manifests can be read first;
                      'podio bleep' then does step 3

        A manifest edited by hand since step 2 wrote it stops the run rather
        than being overwritten; --redetect discards the edits.

        next: import NAME_censored.wav into the NLE, or use 'podio finish' to
        mux each take over its video as well.
        """,
    )
    add_episode_arguments(p_run)
    add_clean_arguments(p_run)
    detect = p_run.add_argument_group("step 2, detect")
    add_detect_arguments(
        detect, wordlist_default=None, wordlist_help=episode_wordlist
    )
    add_redetect(detect)
    detect.add_argument(
        "--review",
        action="store_true",
        help="stop after step 2, so the manifests can be read before step 3",
    )
    p_run.set_defaults(func=_cmd_run)

    p_finish = command(
        "finish",
        """
        steps 1-4 of the pass: clean, detect, bleep and mux every take.

        For every take in audio.toml, or only the TAKES named, each with a
        NAME.mp4 beside it:

          1  clean    ──▶ podio_artifacts/NAME_prepped.wav
          2  detect   ──▶ podio_artifacts/NAME_manifest.json
                          + podio_artifacts/NAME_transcript.json
          3  bleep    ──▶ podio_artifacts/NAME_censored.wav
          4  mux      NAME.mp4 + censored take ──▶ NAME_muxed.mov

        Every NAME.mp4 must exist before step 1 starts. The muxed MOVs land
        beside the inputs; everything else stays under podio_artifacts. A
        take with censoring off skips steps 2-3 and muxes its prepped take.
        A manifest edited by hand stops the run, as in 'podio run'.

        next: import NAME_muxed.mov into the NLE; after exporting the mix,
        'podio master'.
        """,
    )
    add_episode_arguments(p_finish).add_argument(
        "--artifacts",
        type=Path,
        default=Path("podio_artifacts"),
        help="where steps 1-3 write, relative to the episode "
             "(default: podio_artifacts)",
    )
    add_clean_arguments(p_finish, partial=False)
    detect = p_finish.add_argument_group("step 2, detect")
    add_detect_arguments(
        detect, wordlist_default=None, wordlist_help=episode_wordlist
    )
    add_redetect(detect)
    p_finish.set_defaults(func=_cmd_finish, review=False)

    p_clean = command(
        "clean",
        """
        step 1 of the pass: clean every take into a prepped take.

        For every take in audio.toml, or only the TAKES named:

          1  measure  the noise floor: the 10th percentile of 1-second
                      windows, so "floor+N" values in the chain can resolve
          2  chain    the rig's enabled stages, with the episode's overrides,
                      at 48 kHz
          3  meter    integrated loudness and true peak after the chain
          4  gain     one constant gain to the working level (default -24
                      LUFS), held under the peak ceiling (default -2 dBTP)
          ──▶ NAME_prepped.wav, 24-bit, 48 kHz

        Then audio_analysis.toml, recording what was measured and resolved.

        Stopping early:
          --dry-run   after 1, printing each resolved chain; writes nothing
          --range     renders only a slice, to NAME_audition.wav

        Nothing is transcribed or censored. next: 'podio detect' on each
        prepped take, or 'podio run' for steps 1-3 together.
        """,
    )
    add_episode_arguments(p_clean)
    add_clean_arguments(p_clean)
    p_clean.set_defaults(func=_cmd_clean)

    p_man = command(
        "detect",
        """
        step 2 of the pass, on one file: find the words to bleep.

          1  transcribe  WhisperX: every word, with its timing (the first run
                         downloads the model)
          2  match       whole words and phrases from the wordlist, never
                         substrings; the allowlist is never matched
          3  adjust      drop spans under --min-confidence, shrink each edge
                         by --inset, merge what still overlaps
          ──▶ OUT (default manifest.json): the spans to bleep
          ──▶ NAME_transcript.json beside it, where NAME is OUT's name
              without _manifest: every word heard

        Renders no audio. next: read or edit the manifest, then 'podio bleep'.
        """,
    )
    p_man.add_argument("audio", help="the audio to transcribe, e.g. a prepped take")
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
        step 3 of the pass, on one file: put the tone over every span.

          1  decode   AUDIO at its own rate, as mono
          2  splice   a sine tone (1 kHz, --freq) at -27 dBFS RMS over each
                      span MANIFEST lists; every other sample is untouched
          ──▶ OUT (default censored.wav)

        OUT's extension picks the output: .wav is 24-bit audio; .mov or .mkv
        put the 24-bit audio back over AUDIO's video; anything else does the
        same but has to encode the audio to AAC.

        Nothing is transcribed: what the manifest lists is what gets bleeped,
        which is how a manifest edited by hand is rendered.
        """,
    )
    p_bleep.add_argument("audio", help="the audio to censor, e.g. a prepped take")
    p_bleep.add_argument("manifest", help="the spans to bleep, from 'podio detect'")
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
        step 4 of the pass, on one file: put a finished track over a video.

          VIDEO + AUDIO ──▶ picture copied, audio replaced ──▶ OUT

        OUT defaults to VIDEO_muxed.mov. .mov and .mkv copy the wav in as
        it is; anything else re-encodes it to AAC. Nothing is synced or
        mixed: that happens in the NLE.
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

    p_master = command(
        "master",
        """
        step 5 of the pass, after the NLE: bring the exported mixdown to
        delivery loudness, -16 LUFS integrated under -1 dBTP.

          1  measure  integrated loudness of VIDEO's first audio stream
          2  gain     one constant gain to -16 LUFS
          3  limit    a true-peak limiter: 4x oversampled, -1.5 dB ceiling
          4  correct  limiting costs loudness, so 2-3 run again with the
                      shortfall added, until within 0.2 LU (at most 4 times)
          5  encode   ──▶ STEM.mp4  the picture copied, 192 kbps AAC
                      ──▶ STEM.mp3  the feed, 128 kbps, 44.1 kHz
          6  verify   both are metered; WARN if either misses -16 by more
                      than 1 LU or peaks over -1 dBTP

        Takes are untouched: they stay at the working level, and this is the
        only step that sets loudness on the mix.
        """,
    )
    p_master.add_argument("video", help="the NLE's exported mixdown")
    p_master.add_argument(
        "--out", default=None,
        help="output path without extension (default: VIDEO_mastered)",
    )
    p_master.set_defaults(func=_cmd_master)

    p_devices = command(
        "devices",
        """
        standalone, outside the pass: list the microphones a bumper can be
        recorded from.

        Records nothing. Numbers this machine's capture devices so that
        'podio bumper --device N' can name one. The numbers shift when a
        device connects; the name printed beside each one does not.
        """,
    )
    p_devices.set_defaults(func=_cmd_devices)

    p_bumper = command(
        "bumper",
        """
        standalone, outside the pass: record an intro, outro or transition.

          microphone ──▶ ffmpeg capture ──▶ OUT, mono 48 kHz 24-bit

        Captured through OpenAL; on Linux, pulse or alsa if OpenAL finds
        nothing.

        No chain and no gain match: a bumper is recorded deliberately in one
        go, and there is nothing to match it against. It comes out the same
        shape as a prepped take, so it drops onto the timeline beside one.
        Press q to stop. An existing OUT is kept unless --force.
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

    p_norm = command(
        "normalize",
        """
        standalone, outside the pass: decode any audio to 16 kHz mono wav.

          AUDIO ──▶ ffmpeg decode ──▶ OUT, 16 kHz mono

        Nothing in the pass needs this: detection hands audio to WhisperX
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
