# Handoff — podio, 2026-08-09

Working directory: `/Users/jreynolds/tech/audio_processing/bleep-pipeline` (branch `main`,
clean, pushed to `origin/main` at `ef9852e`). Untracked: this file.

## What happened this session

Started as a bug report, ended in an open design question. The design question is the
live thread.

1. **Bug** — `podio run ian.wav` in an episode directory failed with
   `no take named ian.wav in audio.toml`. Cause: a take is named by its TOML table key
   (`[takes.ian]`), not by its `file`. Correct invocation is `podio run ian`. The error
   named no alternatives, which is what made it opaque.
2. **Fix** — `433bfba`. Extracted `select_takes` in `src/podio/clean.py` (pure, so it is
   testable without ffmpeg on PATH) and made the message list the takes that exist.
   New `tests/test_clean.py`, 3 tests.
3. **Cleared the working tree** — the user then asked what the pre-existing uncommitted
   changes were and to commit them:
   - `cf0c57e` — deleted a stray 10.5k-line `nohup.out` committed by accident in `e67cbd5`.
   - `775e7c4` — the bumper-recording feature that was already sitting uncommitted
     (`podio devices`, `podio bumper`, `src/podio/capture.py`, the `$PODIO_FFMPEG`
     install-wrapper mechanism, `ffmpeg-full` in the flake). Not written this session —
     only reviewed, grouped, and committed. Rationale lives in the commit body, the
     `capture.py` module docstring, and README "Why OpenAL, and not avfoundation".
   - `ef9852e` — the same measurement was quoted as 0.02% in `capture.py` and 0.06% in
     README. No record survived of which run produced which, so on the user's decision
     both now read "under 0.1%".
4. **Pushed** `e67cbd5..ef9852e`.

Suite: 151 passing (`just test`, or `uv run pytest -q`).

## The live thread: a "commentary" analysis tool

The user is considering one more tool. Their framing: a full run leaves two per-host
transcripts in JSON; they want a consistent, **mostly deterministic**, repeatable
analysis over the source material that they could **publish alongside the episode**.

My recommendation, given at the end of the session and not yet acted on:

- **Split the deterministic layer from the prose.** Layer 1 is `episode.stats.json`, a
  pure function of the two `*.transcript.json` files plus the manifests — no ffmpeg, no
  model, no network, versioned like `Manifest`/`Transcript`. Layer 2 is prose, rendered
  from layer 1 through a fixed template (stays deterministic) or by a model (does not,
  and then it does not belong in podio). Recommended the template.
- **Determinism anchors at the transcript, not the audio.** WhisperX varies run to run,
  so the tool must take transcript JSON as input and the transcripts must be archived
  with the episode. "Re-runnable from the .wav" is not a claim that can be made.
- **Mic bleed is the main threat** to any per-speaker statistic — each host's track hears
  the other and ASR transcribes the bleed as that host's words. Episode 18 looks clean
  (ian's transcript starts at 29.0s, so josh's cold open did not leak). Proposed
  deterministic guard: the same normalised word in both transcripts within ~0.2s is
  bleed; attribute to the higher-confidence side, drop from the other, report the count
  as a data-quality line.
- **Alignment precision is tens of ms** — do not publish overlap figures to three decimals.
- **"Interruptions"** is computable (B starts mid-turn of A, A stops within N seconds) but
  is a judgement dressed as a metric, and it is about a named real person. Report it as
  "overlaps that ended a turn" and square it with the co-host before publishing.
- **Candidate metrics**: talk time and share; turn count, median turn, longest monologue;
  words per minute of own speech rather than wall clock; crosstalk seconds; dead air;
  bleeps per host from the manifests; questions; unique words; top content words with
  first-use timestamps.
- **Smallest first step**: `src/podio/analysis.py` with one function — `talk_time` — pure,
  test-first, no CLI. Add metrics one at a time; wire a command once three or four are
  worth printing. Name the artifact in `CONTEXT.md` first: "commentary" collides with the
  ordinary English word, which is exactly what that vocabulary section exists to prevent.

Nothing has been written for this. No files created, no term added to `CONTEXT.md`, no
decision recorded on the name. The user has not yet said go.

## Ground truth for the data shape

Read the types in `src/podio/manifest.py` (`Word`, `CensorSpan`, `Manifest`, `Transcript`)
rather than re-deriving them. Real output to work against, produced by a full run:

- `/Users/jreynolds/creative/yellingatrobots/episode_18/` — complete: both
  `*.transcript.json`, both `*.manifest.json`, both `_censored.wav`. ian 2960 words
  29.0→2695.6s / 5 spans; josh 4991 words 0.8→2703.5s / 6 spans. Shared clock, ~45 min.
- `/Users/jreynolds/creative/yellingatrobots/episode_19/` — partial; josh has no
  transcript or manifest yet. Useful as the "half-run" case any new command must not
  crash on.

Those directories hold multi-GB media. Inspect the JSON with a small script; do not cat it.

## Conventions that bit this session

- Global `~/.claude/CLAUDE.md` governs: terse output, no preamble or summarising, one-line
  rationale before non-trivial actions, **never add an agent as commit co-author**.
- Environment is nix + uv. `uv run pytest -q`, never bare `python`/`pytest` — there is no
  ambient pytest.
- Commit style in this repo: conventional prefix, then a lowercase phrase that states the
  behaviour, not the mechanism (`fix: name the takes there are when none match`). Bodies
  explain why. Committing directly to `main` is this repo's norm.
- Prose style in the codebase — docstrings, README, `CONTEXT.md` — is distinctive: full
  sentences explaining *why*, and `CONTEXT.md` terms carry an `_Avoid_` list of rejected
  synonyms. Match it or the new module will read as foreign.

## Suggested skills

- **`codemode`** — required by the user's global instructions before writing, editing,
  reviewing, or refactoring any code, or adding a dependency or tests. Load it first.
- **`tdd`** — the analysis module is pure functions over fixed JSON, which is the ideal
  case for red-green-refactor. This session's `select_takes` was built that way.
- **`domain-modeling`** — for naming the artifact and adding the term to `CONTEXT.md`
  before code is written, in the existing house style.
- **`codebase-design`** — if the layer-1/layer-2 seam needs arguing through before
  committing to an interface.
- **`code-review`** — before pushing the new module.
