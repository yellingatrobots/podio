# podcast_audio

Cleans the raw per-speaker takes of an episode into NLE-ready WAVs.

In: raw mono WAVs, one per speaker. Out: denoised, leveled, gain-matched
24-bit 48 kHz mono WAVs sitting at a common working level with headroom.

Censoring, syncing, mixing and final distribution loudness all happen afterwards
in the NLE. This tool deliberately stops short of a master —
[ADR 0001](docs/adr/0001-clean-pass-stops-short-of-a-master.md).

---

## Starting a new episode

1. Put the raw WAVs in the episode directory (`ian.wav`, `josh.wav`).
2. Create `audio.toml` beside them — copy this whole thing:

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
../tools/podcast_audio/run.py --dry-run
```

Look at the reported noise floor for each take. Around **−75 dB or lower** is a
quiet room and needs nothing. Materially higher than that means something was
running — see [When a take needs more](#when-a-take-needs-more) below.

4. Render:

```sh
../tools/podcast_audio/run.py
```

About 30 seconds for two takes. You get `ian_clean.wav` and `josh_clean.wav`,
plus `audio.analysis.toml` recording what was measured.

5. Import the clean tracks into Premiere/Kdenlive. They still need syncing —
   the takes are independently recorded and drift by tens of milliseconds.
   Censor, mix, and hit your distribution target there.

## Running

```sh
../tools/podcast_audio/run.py                   # every take, full length
../tools/podcast_audio/run.py ian               # just one take
../tools/podcast_audio/run.py --range 21:30+45  # 45 s starting at 21m30s
../tools/podcast_audio/run.py --dry-run         # measure and resolve, render nothing
```

`--range` writes `ian_audition.wav` instead of `ian_clean.wav`, so auditioning
never overwrites a finished render. Use it to check one specific moment — a
laugh you think got chewed — without re-rendering 35 minutes.

Nothing is installed. The shebang runs the script through `uv`, which reads the
dependency header and builds a throwaway environment. Needs `ffmpeg` on PATH.

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

Vocabulary is in [CONTEXT.md](CONTEXT.md).

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

## Tests

```sh
uv run --with pytest --with pydantic pytest tests/
```

Most are pure. `test_end_to_end.py` drives real ffmpeg over a synthesized take
and asserts the result lands on the working level.
