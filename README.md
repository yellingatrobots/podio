# podio

Written in ASD-STE100 Simplified Technical English.

podio cleans and censors the raw takes of a podcast episode. It makes audio
that is ready for the video editor. It also masters the mixdown from the video
editor for delivery.

In: raw audio files, one for each speaker, at the rate of the recording.
Out: audio files with less noise, at one common level and one common rate
(48 kHz), and a manifest of the words to censor.

```
takes ──▶ chain (denoise, gate, EQ, compress) ──▶ gain match ──▶ prepped take
      ──▶ transcribe (WhisperX) ──▶ detect (word list) ──▶ manifest
      ──▶ put a tone on each span ──▶ censored take ──▶ video editor
mixdown ──▶ master ──▶ mastered mp4 + feed mp3
```

The video editor does the synchronization and the mix. The pass does not set
the delivery loudness on a take — refer to
[ADR 0001](docs/adr/0001-clean-pass-stops-short-of-a-master.md). `podio master`
sets it one time, on the mixdown from the video editor — refer to
[ADR 0003](docs/adr/0003-podio-masters-the-nle-mixdown.md).

## Documents

| Document | Contents |
|---|---|
| [User guide](docs/guide.md) | How to use podio: the steps, the configuration, all the stages, and all the commands. |
| [CONTEXT.md](CONTEXT.md) | The words of this project and their exact meanings. |
| [docs/adr/](docs/adr) | The records of the design decisions. |

To start immediately:

```sh
nix run github:yellingatrobots/podio -- --version
```

## Environment

`uv.lock` sets the version of each Python package. uv installs from it, and
the flake builds from it (with uv2nix), thus the two environments have the
same packages. Nix supplies only the interpreter, ffmpeg, and the tools.
Refer to [ADR 0004](docs/adr/0004-uv-lock-is-the-dependency-source.md).

```sh
nix develop            # ffmpeg, just, uv, python and the dependencies
just                   # shows the tasks
just test              # does the tests
```

In the shell, `podio` is an editable installation of `src/`, thus `podio`
operates the working tree. Your changes are immediately in operation:

```sh
podio --help
nix develop ~/tech/podio -c podio run   # from a directory of an episode
```

To add a dependency, do `uv add NAME` in the shell. uv changes `pyproject.toml`
and `uv.lock`, and direnv builds the shell again. If a Linux build then stops
with a missing `.so` library, add the library to `fixups` in `flake.nix`.

The justfile has only the tasks of the repository (`test`, `install`,
`censor`). Its recipes operate in the repository. For an episode, use `podio`.

`nix run` needs no clone, and the directory of the episode is independent of
the flake:

```sh
nix run github:yellingatrobots/podio -- devices
nix run /path/to/podio -- run
```

The two dashes divide the options of nix from the options of podio.

podio is a package of this flake, thus a machine can install it declaratively.
On the machine of the author, a home-manager module in `~/etc` does this. On a
machine with no such configuration, `just install` does `nix profile install .`.
Do not use `just install` where the home-manager module supplies podio, because
the copy in the profile hides the other copy on the `PATH`.

`$PODIO_FFMPEG` is in the build, thus podio always finds the correct ffmpeg. A
directory of an episode is outside the development shell, and the `ffmpeg` on
that `PATH` is the ffmpeg of the machine.

### Why the tests use one exact ffmpeg

podio reads the loudness and the window levels from the stderr text of ffmpeg.
A new format of that text can stop the parser. The version is not frozen: it
follows the nixpkgs input. But `tests/test_end_to_end.py` operates against that
exact binary during `nix flake check`. A change in the output of ffmpeg thus
stops the check.

The package is `ffmpeg-full`, because this build has the OpenAL capture device.
`podio bumper` records through it.

### Why OpenAL, and not avfoundation

podio records through the OpenAL capture device of ffmpeg on all platforms.

The usual method on macOS is `ffmpeg -f avfoundation -i ":0"`. This method
loses audio and gives no message. Its capture delegate keeps one buffer. When
the next buffer comes, the delegate releases the data that is still in the
first buffer (`libavdevice/avfoundation.m`, `didOutputSampleBuffer`). There is
no queue, and no option makes one. The option `drop_late_frames` applies to
video only.

Tests here measured a loss of 11 % to 17 % of each recording. The losses were
some milliseconds long and occurred many times each second. The samples on the
two sides of a loss become adjacent, and each of these points makes a click.
The clicks are not audible in a quiet room, but they are very audible when a
person speaks.

OpenAL reads through a ring buffer. It lost less than 0.1 % of the same
recordings.

OpenAL records 16-bit audio, and avfoundation records 32-bit float audio. A
complete 16-bit recording is better than a 24-bit recording with holes, and 16
bits are sufficient for speech. On Linux, `pulse` and `alsa` are alternatives.
They do not have this defect, and OpenAL can find no device on a machine with
no sound hardware.

### Without nix

uv uses the same `uv.lock` as nix, thus the packages are the same:

```sh
uv sync                # makes .venv from uv.lock
uv run podio --help
uv run pytest -q
uv tool install .      # puts podio on the PATH
```

uv cannot supply ffmpeg. Install an ffmpeg with the OpenAL capture device, or
set `PODIO_FFMPEG` to the path of one. The lock has three platforms: macOS on
Apple silicon, and Linux on aarch64 and x86_64. On Linux, torch is the CPU-only
build, thus `--asr-device cuda` does not operate.

There is one environment and one interpreter (Python 3.12, in
`.python-version`). WhisperX is a necessary
dependency (approximately 1.1 GB, mostly torch), because the censor function is
part of the pass. The first detection downloads the model data (approximately
141 MB for the default `base.en`). Subsequent detections do not use the
network.

## Design notes

- **One owner of ffmpeg.** `ffmpeg.py` is the only module that starts an
  external process. It uses files and command lines. The other modules use
  samples and values.
- **The ASR is injected.** `detect.transcribe_and_detect` depends on the
  `Transcriber` protocol, not on WhisperX. podio imports WhisperX only when it
  is necessary, thus the core and its tests operate without torch.
- **A pure core.** Normalization (`text.py`), the match of the words
  (`wordlist.py`), the adjustment of the spans (`adjust.py`), the levels
  (`levels.py`), and the tone (`bleep.bleep_pcm`) are pure functions. Their
  tests need no audio and no model.
- **The manifest has no audio.** Detection makes an edit list. A different step
  reads that list and makes the audio.
- **One gain change.** podio brings each take to the working level with one
  constant gain. It does not use `loudnorm` — refer to
  [ADR 0002](docs/adr/0002-static-gain-match-instead-of-loudnorm.md).
- **The version is in one file.** `src/podio/__init__.py` holds `__version__`,
  and hatchling and `flake.nix` read it from there.

## Example — episode 16

A fan was in operation during the recording of Ian. It was not in operation
during the recording of Josh. The two microphones were the same class.

```
ian    floor  -58.8 dB   I -26.0 → gain +2.0 → -24.0 LUFS, TP -2.9
josh   floor  -79.5 dB   I -28.8 → gain +4.8 → -24.0 LUFS, TP -2.3
```

Ian used `afftdn` and `gate`. Josh used neither of them. The noise floor of Ian
went from −58.8 dB to −93.3 dB. The difference of 4.4 LU between the two takes
became zero. The working level is −24 dB, not −20 dB, because these takes have
a crest factor of approximately 21 LU after the chain. A level of −20 dB
clamped the two takes.

## Not yet built

- podio has no phonetic protection for the words that the ASR gets wrong. This
  is the primary risk of a missed word.
- The censored output has one channel. podio mixes a two-channel source to one
  channel.

## License

MIT — refer to [LICENSE](LICENSE). It is permissive. You must keep the notice
of copyright and the notice of permission in all copies.
