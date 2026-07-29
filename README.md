# podio

Cleans and censors the raw per-speaker takes of a podcast episode into
NLE-ready audio.

In: raw mono WAVs, one per speaker. Out: denoised, leveled, gain-matched
24-bit 48 kHz WAVs sitting at a common working level with headroom, and a
reviewable manifest of the spans to bleep.

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
just                   # list tasks
just test              # run the tests
```

`ffmpeg` is pinned by the flake on purpose: podio reads loudness and per-window
levels out of ffmpeg's human-readable stderr, so an upstream formatting change
breaks parsing rather than the build.

There is one environment and one interpreter. WhisperX is a hard dependency
(~1.1 GB installed, mostly torch) because censoring is part of the pass, not an
add-on. **The first detection run downloads model weights** (~141 MB for the
default `base.en`) from Hugging Face; after that it runs offline.

## Cleaning an episode

1. Put the raw WAVs in the episode directory (`ian.wav`, `josh.wav`).
2. Create `audio.toml` beside them:

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

3. See what it makes of them, without rendering anything:

```sh
uv run --project /path/to/podio podio clean --dry-run
```

Look at the reported noise floor for each take. Around **−75 dB or lower** is a
quiet room and needs nothing. Materially higher means something was running —
see [When a take needs more](#when-a-take-needs-more).

4. Render:

```sh
uv run --project /path/to/podio podio clean
```

About 30 seconds for two takes, plus `audio.analysis.toml` recording what was
measured. Worth an alias — `alias podio='uv run --project /path/to/podio podio'`
— after which everything below is just `podio clean`.

```sh
podio clean                   # every take, full length
podio clean ian               # just one take
podio clean --range 21:30+45  # 45 s starting at 21m30s
podio clean --dry-run         # measure and resolve, render nothing
```

`--range` writes `ian_audition.wav` instead, so auditioning never overwrites a
finished render. Use it to check one moment — a laugh you think got chewed —
without re-rendering 35 minutes.

## Censoring

Detection and rendering are separate, so the manifest can be reviewed before
anything is spliced.

```sh
podio detect ian.wav --out ian.manifest.json    # -> manifest + transcript
podio bleep ian.wav ian.manifest.json --out ian_censored.wav
just censor test_audio/profanity.m4a out.wav    # one-shot, to just hear it
```

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

### Wordlist

`config/wordlist.toml` holds the terms and an `allowlist` of whole words that
must never be censored. Matching is whole-word or whole-phrase, case- and
punctuation-insensitive, and never substrings — so "class", "assassin" and
"cockpit" are safe (the Scunthorpe problem).

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

The repositories behind this tool were merged recently and the behavioural half
of that work is still outstanding. As it stands:

- **Censoring is not yet wired into the clean pass.** `detect` and `bleep` work
  on whatever file you point them at; they don't yet run automatically over a
  prepped take, and there is no `podio run`.
- **The tone level is hardcoded** at roughly −8.7 dBFS, which is about 12 dB
  hotter than a −24 LUFS working level. It should derive from the working level.
- A phonetic safety net for words the ASR mis-transcribes — the main
  false-negative risk — does not exist.
- The censored output is mono; a stereo source is downmixed.

## License

MIT — see [LICENSE](LICENSE). Permissive; requires that the copyright and
permission notice be preserved in copies (attribution).
