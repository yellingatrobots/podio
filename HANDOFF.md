# Handoff — bleep-pipeline

**For:** the next session, which will build the **next phase (Stage 5: span post-processing)**.
**Repo:** `~/tech/bleep-pipeline` (own git repo, branch `main`).
**Last commit:** `fadf5c0` — scaffold of the offline detection slice.

Read `README.md` first — it has the architecture, run commands, design notes, and
the "Not yet built" list. This doc only adds what isn't already captured there or
in the code/commit.

## Where things stand

The **detection slice is complete and verified** (README covers stages 1, 2, 4):
audio → ffmpeg normalize → WhisperX (word timestamps) → whole-word matching →
`manifest.json` + sibling `*.transcript.json`. 11 unit tests green. Smoke-tested
end-to-end on `test_audio/` (2 spans on profanity, 0 on clean).

## Next phase — Stage 5: span post-processing

Full spec is in `README.md` → "Not yet built". Summary of the user's intent:

- **No padding.** Apply a slight **negative inset (shrinkage)** so the onset of the
  first consonant and the tail of the last stay audible (user wants to hear the
  "f" and "k" of "fuck").
- Make the **inset amount a parameter** so the user can dial in how much edge stays.
- Drop any span that collapses to ≤ 0 width after inset; **merge spans that overlap
  after inset**.
- Snap each voice↔bleep transition to a **zero-crossing** (or a ~2–3ms micro-fade)
  to avoid click artifacts. (Zero-crossing = waveform amplitude ≈ 0; cutting elsewhere
  creates a step discontinuity heard as a click.)

This stage is **pure and unit-testable** — it transforms the `find_spans` output
(a list of `CensorSpan`), no audio or ML needed. Build it test-first as a new module
(e.g. `src/bleep/postprocess.py`) with `tests/test_postprocess.py`.

After Stage 5 comes **Stage 6 (the actual bleep renderer)**: consume the manifest,
generate 1 kHz tone, duck the original, splice into the full-quality source. That
one does touch audio and will need a real run to verify.

## How to work in this repo (gotchas)

- **Enter env:** `nix develop`, then `just` to list tasks. `just test` runs the pure
  tests in the plain nix shell (no ML install needed).
- **Nix flakes only see git-tracked files.** After creating new files, `git add -A`
  before `nix develop` or the flake errors with "not tracked by Git".
- **Running the ASR path:** `just setup-asr` first (installs WhisperX + torch, ~2 GB
  into `.venv`). Real transcription runs via `.venv/bin/python` with `PYTHONPATH=src`;
  ffmpeg comes from the nix shell. See the `manifest` recipe in the `justfile`.
- **Models:** `base.en` was used for fast smoke tests; the CLI default is `large-v3`
  (production accuracy, slow on CPU).
- **Non-fatal warning:** WhisperX prints a `torchcodec` `dlopen` traceback (its bundled
  ffmpeg dylibs don't resolve against the nix ffmpeg). Harmless — it falls back and we
  feed it a normalized WAV. Suppressible later by aligning torchcodec/ffmpeg versions.
- **Artifacts:** `test_audio/*.m4a` are committed fixtures. Run outputs
  (`manifest*.json`, `*.transcript.json`) are gitignored — do not commit them.

## Working style the user expects (learned this session)

- **Tight XP loop:** ONE small module + its test, run green, then **check in** before
  the next unit. Do not batch-write many files.
- **No vacuous tests.** Don't test glue/passthrough with fakes that just re-assert
  logic already covered elsewhere — verify glue by **running it for real** instead.
- **No leetspeak/obfuscation normalization.** This is a *transcript* process; the ASR
  emits correctly-spelled words. Keep `text.normalize` minimal.
- **Terminology:** it's a "transcriber interface" (not a "seam").
- **Avoid jargon / over-explaining** in commit messages and prose.
- **Commits:** conventional style; **never** add an agent as co-author.
- **Packaging:** run-in-place via `PYTHONPATH`; no setuptools/build backend unless a
  real need appears.

## Suggested skills for the next session

- **`tdd`** — Stage 5 is pure logic; ideal for red-green-refactor. Start here.
- **`verify`** — after Stage 5 (and especially Stage 6), verify by exercising the flow
  on `test_audio/` fixtures, not just unit tests.
- **`code-review`** — before committing the phase, review the diff against the repo's
  standards.

## Open item

`git push` was requested but there is **no remote** and `gh` is not authenticated, so
nothing was pushed. To publish: `gh auth login`, create a remote (e.g.
`gh repo create bleep-pipeline --private --source . --remote origin`), then `git push -u origin main`.
