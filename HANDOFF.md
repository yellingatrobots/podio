# Handoff — bleep-pipeline

**For:** the next session, which will build **Stage 6: the bleep renderer**.
**Repo:** `~/tech/bleep-pipeline` (own git repo, branch `main`).
**Last commit:** `e48a8bd` — Stage 5 wired into the pipeline.

Read `README.md` first — architecture, run commands, design notes, and the "Not
yet built" list. This doc only adds what isn't already captured there or in the
code/commit.

## Where things stand

Detection (stages 1, 2, 4) **and Stage 5 post-processing are complete and
verified.** Flow: audio → ffmpeg normalize → WhisperX (word timestamps) →
whole-word matching (`find_spans`) → **post-process (inset → drop → merge)** →
`manifest.json` + sibling `*.transcript.json`. 16 unit tests green.

Stage 5 (`src/bleep/postprocess.py`, pure) does:
- **Negative inset** — shrink each span inward by `--inset` seconds per edge
  (default 0.03) so the first consonant onset and last tail stay audible.
- **Drop** spans that collapse to <= 0 width after inset.
- **Merge** spans that still overlap; the merged span joins both words' `term`
  and `source_text` and takes the minimum `confidence`.

It's wired into `transcribe_and_detect`, exposed as `manifest --inset`.
Smoke-tested end-to-end on `test_audio/`: at `--inset 0.03` both spans shrink
30ms per edge vs `--inset 0` (fuck 360->300ms); profanity → 2 spans, clean → 0.

**Note:** `severity` was removed this session (it was informational only) and the
wordlist was trimmed to high-only terms.

## Next phase — Stage 6: the bleep renderer

Consume the manifest and produce censored audio: generate a 1 kHz tone, duck (or
replace) the original under each span, and splice into the full-quality source.
This one **touches audio**, so verify it with a real run on `test_audio/`, not
just unit tests. Keep it simple — no zero-crossing/micro-fade machinery unless a
real click problem shows up in a rendered file.

## How to work in this repo (gotchas)

- **Enter env:** `nix develop`, then `just` to list tasks. `just test` runs the
  pure tests in the plain nix shell (no ML install needed).
- **Nix flakes only see git-tracked files.** After creating new files, `git add -A`
  before `nix develop` or the flake errors with "not tracked by Git".
- **Running the ASR path:** `.venv` already exists (WhisperX + torch). Real
  transcription runs via `.venv/bin/python` with `PYTHONPATH=src`; ffmpeg comes
  from the nix shell. See the `manifest` recipe in the `justfile`.
- **Models:** use `--model base.en` for fast smoke tests; the CLI default is
  `large-v3` (production accuracy, slow on CPU).
- **Non-fatal warning:** WhisperX prints a `torchcodec` `dlopen` traceback. Harmless
  — it falls back and we feed it a normalized WAV.
- **Artifacts:** `test_audio/*.m4a` are committed fixtures. Run outputs
  (`manifest*.json`, `*.transcript.json`) are gitignored — do not commit them.
  Write scratch run outputs to the session scratchpad, not the repo.

## Working style the user expects

- **Tight XP loop:** ONE small unit + its test, run green, then **check in**
  before the next unit. Do not batch-write many files.
- **KISS.** Do the simplest thing; don't add machinery for problems you don't
  yet have. The user will trim scope aggressively (e.g. removed severity).
- **No vacuous tests.** Don't test glue/passthrough with fakes — verify glue by
  **running it for real** (that's how Stage 5's wiring was verified).
- **Never say "seam."** Call it the public interface / entry point.
- **No leetspeak/obfuscation normalization** — it's a transcript process; keep
  `text.normalize` minimal.
- **Avoid jargon / over-explaining** in commits and prose.
- **Commits:** conventional style; **never** add an agent as co-author.
- **Packaging:** run-in-place via `PYTHONPATH`; no build backend.

## Open item

`git push` was requested earlier but there is **no remote** and `gh` is not
authenticated, so nothing was pushed. To publish: `gh auth login`, create a
remote (e.g. `gh repo create bleep-pipeline --private --source . --remote origin`),
then `git push -u origin main`.
