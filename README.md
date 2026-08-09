# podio

Cleans and censors the raw per-speaker takes of a podcast episode into
NLE-ready audio.

In: raw mono WAVs, one per speaker, at whatever rate they were recorded at. Out:
denoised, leveled, gain-matched 24-bit WAVs at a common working rate (48 kHz
unless the episode says otherwise), sitting at a common working level with
headroom, and a reviewable manifest of the spans to bleep.

Syncing, mixing and final distribution loudness happen afterwards in the NLE.
This tool deliberately stops short of a master —
[ADR 0001](docs/adr/0001-clean-pass-stops-short-of-a-master.md).

Vocabulary is in [CONTEXT.md](CONTEXT.md); it is worth reading first, because
the words below (*take*, *rig*, *stage*, *span*, *manifest*) are used precisely.

```
takes ──▶ chain (denoise, gate, EQ, compress) ──▶ gain match ──▶ prepped take
      ──▶ transcribe (WhisperX) ──▶ detect (wordlist) ──▶ manifest
      ──▶ splice tone ──▶ censored take ──▶ NLE
```

## Environment

Nix supplies the system binaries; `uv` supplies the Python.

```sh
nix develop            # ffmpeg, just, uv
just sync              # build the environment from uv.lock
just install           # put `podio` on your PATH
just                   # list tasks
just test              # run the tests
```

`just install` puts `podio` into `~/.local/bin` (pass another directory as
`just install ~/bin`) as a two-line wrapper. It execs this repo's own entry
point, so there is still one environment and edits here take effect immediately
— but it also records the dev shell's `ffmpeg` in `$PODIO_FFMPEG` on the way
past. That matters because an episode directory is outside the dev shell, and
the `ffmpeg` found there is whatever the machine happens to have: podio parses
ffmpeg's human-readable output, and records through an OpenAL capture device
that the default builds leave out. **Re-run `just install` after
`nix flake update`**, when the store path it recorded moves — a path that no
longer resolves falls back to whatever is on `PATH` rather than failing, so
cleaning still works and only recording complains.

`ffmpeg` is pinned by the flake on purpose: podio reads loudness and per-window
levels out of ffmpeg's human-readable stderr, so an upstream formatting change
breaks parsing rather than the build. It is `ffmpeg-full` specifically, because
that is the build carrying the OpenAL capture device that `podio bumper` records
through — see [Why OpenAL, and not avfoundation](#why-openal-and-not-avfoundation).

There is one environment and one interpreter. WhisperX is a hard dependency
(~1.1 GB installed, mostly torch) because censoring is part of the pass, not an
add-on. **The first detection run downloads model weights** (~141 MB for the
default `base.en`) from Hugging Face; after that it runs offline.

## Cleaning an episode

1. Put the raw WAVs in the episode directory (`ian.wav`, `josh.wav`).
2. Run `podio run`. With no `audio.toml` there it shows you one built from the
   takes it found and offers to write it — each `.wav` becomes a take pointed at
   the rig of the same name, and podio's own outputs are never mistaken for
   takes. Decline, and you get the usual missing-config error and can write it
   yourself:

```toml
# Episode NN.

working_level_db = -24.0
peak_ceiling_db  = -2.0

[takes.ian]
file = "ian.wav"
rig  = "ian"

[takes.josh]
file = "josh.wav"
rig  = "josh"
```

`working_level_db = -24.0` and `peak_ceiling_db = -2.0` are what you get whether
you write them or leave them out — the scaffold puts them in so they are visible
and easy to change, not because omitting them means something else. The 22 dB
between them is what a take's peak-to-loudness ratio has to exceed before the
gain match clamps, which is comfortably clear of conversational speech even with
a laugh in it.

The chain runs at 48 kHz and prepped takes are written at it. That is not
configurable: it is what video work expects, and it is the only rate `rnnoise`
can run at. A take arriving at any other rate is brought over once, before the
chain.

3. See what it makes of them, without rendering anything:

```sh
podio run --dry-run
```

Look at the reported noise floor for each take. Around **−75 dB or lower** is a
quiet room and needs nothing. Materially higher means something was running —
see [When a take needs more](#when-a-take-needs-more).

4. Render:

```sh
podio run
```

About 30 seconds of cleaning per two takes, plus detection, plus
`audio.analysis.toml` recording what was measured.

To clean without censoring:

```sh
podio clean                   # every take, full length
podio clean ian               # just one take
podio clean --range 21:30+45  # 45 s starting at 21m30s
podio clean --dry-run         # measure and resolve, render nothing
```

`--range` writes `ian_audition.wav` instead, so auditioning never overwrites a
finished render. Use it to check one moment — a laugh you think got chewed —
without re-rendering 35 minutes.

## The whole pass

`podio run` does everything: cleans each take, detects against the *prepped*
take, and splices the tone on last.

```sh
podio run                 # clean + censor every take
podio run ian             # just one take
podio run --review        # stop after detection, before anything is spliced
podio run --redetect      # re-detect even over hand-edited manifests
```

An episode directory afterwards:

```
ian.wav                raw take
ian_prepped.wav        cleaned, gain-matched, uncensored
ian_censored.wav       ← import this one
ian.manifest.json      the spans, reviewable and editable
ian.transcript.json    every word heard, with timings
audio.analysis.toml    what the run measured
```

Detection listens to the prepped take, not the raw one — denoising and gating
measurably help the ASR — and the tone goes on after gain match, so it never
passes through the compressor or the gate, which would pump a constant sine.

**Editing a manifest.** Edit `ian.manifest.json` and re-render it in about a
second with `podio bleep ian_prepped.wav ian.manifest.json --out
ian_censored.wav` — no ASR, no chain. A later `podio run` will *stop* rather than
overwrite an edited manifest, because detection is reproducible and your
judgement about a word it got wrong is not. `--redetect` overrides that and
discards the edits. (Detection writes the manifest and transcript together;
a manifest newer than its transcript is one a human touched.)

`--range` auditions the chain only and censors nothing: a slice's manifest would
be timed against the slice rather than the take.

## Censoring on its own

The two halves are separate commands too, for a file that isn't part of an
episode:

```sh
podio detect ian.wav --out ian.manifest.json    # -> manifest + transcript
podio bleep ian.wav ian.manifest.json --out ian_censored.wav
just censor test_audio/profanity.m4a out.wav    # one-shot, to just hear it
```

For video, `mux` puts a finished track over the picture:

```sh
podio mux episode.mp4 alex_censored.wav --out episode_censored.mov
podio mux episode.mp4 alex_censored.wav      # -> episode_muxed.mov
```

Neither stream is re-encoded: the picture is copied through and the WAV is
copied in as PCM, so the censored audio arrives in the NLE exactly as the
pipeline rendered it. That is what the `.mov` is for — MP4 cannot carry PCM
dependably, so a `.mp4` output re-encodes the audio to AAC and costs a
generation. `.mov` and `.mkv` copy.

(`podio bleep` muxes implicitly when its `--out` is a video file: it bleeps the
source's own audio and puts it straight back over the picture, same rule.)

Each `detect` run writes two files: the manifest (spans to bleep) and a sibling
`*.transcript.json` (every word with its timing) — the lean edit list and the
auditable record. When you suspect a word was missed, the transcript is what you
grep.

A span looks like:

```json
{
  "start": 12.34, "end": 12.71,
  "term": "fuck",
  "source_text": "Fuck!", "confidence": 0.98
}
```

Spans are adjusted before the manifest is written. `--inset SECONDS` (default
0.03) shrinks each span edge inward so the onset of the first consonant and the
tail of the last stay audible — you hear the "f" and the "k". `--inset 0`
disables it. Spans that collapse to nothing are dropped; spans that still
overlap are merged. `--min-confidence FLOAT` (default 0) drops shaky detections,
leaving them for review rather than bleeping blindly.

`--model` is a WhisperX model name — `base.en` by default, `large-v3` for
accuracy at the cost of speed.

### What gets censored

Censoring is configured in the episode, like everything else that varies per
recording:

```toml
[censor]
enabled  = true           # default; false leaves the episode uncensored
wordlist = "extra.toml"   # optional, relative to the episode directory

[takes.ian.censor]
enabled = false           # this take only
```

The tone itself is not configurable. It is fixed at −27 dBFS RMS, three dB under
the −24 working level the clean step brings every take to, which puts its peak at
−24 dBFS — plainly audible against speech, nowhere near the peak ceiling, and not
the loudest thing in the episode. Equal-RMS with speech would read as *louder*
than speech, because the tone is continuous, narrowband, and near the ear's most
sensitive region. If the working level ever moves, change `TONE_LEVEL_DB` in
`levels.py` with it.

### Wordlist

`config/wordlist.toml` holds the terms and an `allowlist` of whole words that
must never be censored. Matching is whole-word or whole-phrase, case- and
punctuation-insensitive, and never substrings — so "class", "assassin" and
"cockpit" are safe (the Scunthorpe problem).

## Recording a bumper

Intros, outros and transitions are recorded rather than cleaned, so podio can
capture them directly and hand the NLE a file already at the working rate:

```sh
podio devices                        # what this machine can hear through
podio bumper                         # -> bumper.wav, press q to stop
podio bumper outro.wav --device 2    # a number from `podio devices`
```

A bumper is captured mono at 48 kHz and written 24-bit — the same shape as a
prepped take, so it drops onto the timeline beside one without conversion. It
does not go through the chain: there is nothing to gain-match it against, and a
bumper is usually recorded in one deliberate go rather than salvaged.

`podio bumper` is the only command that refuses to overwrite its output. Every
other one can be run again from its inputs; a recording cannot, so replacing one
takes `--force`.

The numbers `podio devices` prints are podio's own, and are positions in that
listing — they shift when a device connects, so a pair of headphones can
renumber everything below it. `--device` also takes a device name straight
through, which is the stable way to write it down:

```sh
podio bumper --device "RØDE PodMic USB"
```

With no `--device`, podio records from whichever microphone the system itself is
using.

### Why OpenAL, and not avfoundation

podio records through ffmpeg's **OpenAL** capture device on every platform, and
that is the reason the dev shell wants `ffmpeg-full` rather than `ffmpeg`.

The obvious way to record on macOS — `ffmpeg -f avfoundation -i ":0"`, which is
what every recipe online gives — silently **loses audio**. Its capture delegate
holds one buffer slot and releases whatever is still in it when the next buffer
arrives, so anything not collected in time is dropped
(`libavdevice/avfoundation.m`, `didOutputSampleBuffer`). There is no queue and
no option that adds one; `drop_late_frames` only reaches the video path.
Measured here it lost 11–17% of every recording, in gaps of a few milliseconds
tens of times a second. The samples either side get spliced together, and every
splice is a click — inaudible in a silent room and obvious the moment anyone
speaks, which makes it look like a broken microphone rather than a broken
capture. OpenAL reads through a ring buffer and lost under 0.1% of the same
recordings.

The one thing given up is depth: OpenAL captures at 16 bits, where avfoundation
offered 32-bit float. A complete 16-bit recording beats a 24-bit one with holes
in it, and 16 bits is ample for a spoken bumper. On Linux, `pulse` and `alsa`
remain as fallbacks — they do not share the defect, and OpenAL may find nothing
to talk to on a headless box.

## When a take needs more

Everything below is edited in the episode's `audio.toml`, never in the rig.
Re-run after each change; it takes seconds.

| What you hear | What to change |
|---|---|
| Steady hum, fan, aircon, traffic | `[takes.X.afftdn] enabled = true`. Raise `reduction_db` from 12 if it's still there. |
| Room tone breathing between phrases | `[takes.X.gate] enabled = true` |
| Gate chewing laughter or quiet words | Raise the offset: `threshold_db = "floor+8"`. Or lengthen `release_ms` past 250 so gaps inside a laugh don't each read as silence. |
| Noise `afftdn` can't shift | `[takes.X.rnnoise] enabled = true`. `model = "lq"` for ambient noise, `"bd"` for equipment hiss. Needs `$RNNOISE_MODELS` set. Listen for chewed laughter — it judges voice vs not-voice. |
| Boomy, too much chest | `[takes.X.highpass] f = 100`, or an EQ band in the **rig** if it's always that way |
| Harsh S sounds | `[takes.X.deesser] intensity = 0.6` |
| Delivery wanders loud to quiet | `[takes.X.compressor] ratio = 4` |

If a take is *very* different from usual — a hotel room, a different mic — it is
still an episode-level change. Rigs describe the stable setup; conditions belong
to the episode.

### "gain clamped at the peak ceiling"

The take's peaks won't allow enough gain to reach the working level without
breaching `peak_ceiling_db`, so the tool backed the gain off and told you rather
than clipping. The message says how far under it landed. Either:

- lower `working_level_db` until it clears (headroom is free on an intermediate), or
- set `limiter = true` on that take, which lets it reach the target by shaving peaks.

A few LU under the working level is harmless. Takes drifting apart from *each
other* is what matters, and that only happens when one clamps and the other
doesn't.

## Configuring

Two layers.

A **rig** (`rigs/ian.toml`) is a speaker's stable setup and owns the full ordered
chain — every stage listed, with the condition-dependent ones switched off. Only
stages the rig lists can be overridden, which is why they are all enumerated.

An **episode** (`episode_NN/audio.toml`) says which rig each take uses and turns
on whatever that recording needs.

```toml
[takes.ian]
file = "ian.wav"
rig  = "ian"

[takes.ian.afftdn]      # a fan was running this episode
enabled = true
```

Levels are in **dB everywhere** — the tool converts to whatever units the
underlying ffmpeg filter wants. A value may also be measured rather than fixed:
`"floor+12"` means twelve dB above this take's noise floor, so a chain adapts to
a new room without being re-tuned.

Noise floor is the 10th percentile of one-second windows, not the quietest
moment — an edit or a dropout is silence, not room tone.

## The chain

`highpass → afftdn → rnnoise → gate → eq → compressor → deesser`, then gain
match, then the limiter if the take asked for one.

| stage | for | notes |
|---|---|---|
| `highpass` | rumble, plosives, proximity effect | |
| `afftdn` | steady broadband noise | leaves laughter alone; reach for this first |
| `rnnoise` | noise `afftdn` can't reach | can chew laughter; needs `$RNNOISE_MODELS` |
| `gate` | room tone between phrases | `threshold_db = "floor+12"` |
| `eq` | corrective/tonal | belongs in the rig |
| `compressor` | evening out delivery | the only stage that should touch dynamics |
| `deesser` | sibilance | after the compressor, which raises it |

Takes are brought to the working level by one constant gain measured at the end
of the chain — no `loudnorm`, for the reasons in
[ADR 0002](docs/adr/0002-static-gain-match-instead-of-loudnorm.md).

## Worked example — episode 16

Ian recorded with a fan running; Josh didn't. Same class of mic both sides.

```
ian    floor  -58.8 dB   I -26.0 → gain +2.0 → -24.0 LUFS, TP -2.9
josh   floor  -79.5 dB   I -28.8 → gain +4.8 → -24.0 LUFS, TP -2.3
```

Ian got `afftdn` and `gate` switched on; Josh got neither. Ian's floor went
−58.8 → −93.3 dB, and the 4.4 LU loudness gap between the two of them closed to
zero. Working level is −24 rather than −20 because these takes have a ~21 LU
crest factor after cleanup, and −20 clamped both.

## Design notes

- **One ffmpeg owner.** `ffmpeg.py` is the only module that shells out; it deals
  in files and command lines, everything else in samples and values.
- **Injected ASR.** `detect.transcribe_and_detect` depends on the `Transcriber`
  protocol, not WhisperX. WhisperX is imported lazily, so the core and its tests
  run without loading torch.
- **Pure core.** Normalization (`text.py`), matching (`wordlist.py`), span
  adjustment (`adjust.py`), levels (`levels.py`) and the tone splice
  (`bleep.bleep_pcm`) are pure functions, unit-tested without audio or models.
- **The manifest is audio-agnostic.** Detection produces an edit list; rendering
  is a separate concern that consumes it.

## Not yet built

- A phonetic safety net for words the ASR mis-transcribes — the main
  false-negative risk — does not exist.
- The censored output is mono; a stereo source is downmixed.

## License

MIT — see [LICENSE](LICENSE). Permissive; requires that the copyright and
permission notice be preserved in copies (attribution).
