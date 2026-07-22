# bleep-pipeline

Offline, AI-driven pipeline that detects profanity in an audio file and emits a
**censor manifest** — an edit list of spans to bleep. Batch/offline: highest
accuracy, no latency budget. A human can review the manifest before rendering.

This is the **detection slice** (stages 1, 2, 4). Audio rendering (the actual
bleep) is a separate downstream stage that consumes the manifest.

```
audio ──▶ normalize (ffmpeg) ──▶ transcribe (WhisperX, word timestamps)
      ──▶ detect (wordlist) ──▶ manifest.json
```

## Environment

Dependencies and runtime come from Nix; tasks run through `just`.

```sh
nix develop            # enter the dev shell (python, ffmpeg, just, uv)
just                   # list tasks
just test              # fast unit tests — no ML deps required
```

The heavy ASR stack (WhisperX + torch) is **not** in the nix shell; install it on
demand into a local venv:

```sh
just setup-asr         # uv venv .venv + whisperx
```

## Run

```sh
just normalize input.mp3            # debug: -> normalized.wav (16kHz mono)
just manifest input.mp3             # -> manifest.json (needs setup-asr first)
just manifest input.mp3 out.json config/wordlist.yaml
```

Each `manifest` run writes two files: the manifest (spans to bleep) and a
sibling `*.transcript.json` (the full word list with timestamps) — the lean
edit-list and the auditable record, respectively. `out.json` yields
`out.transcript.json`.

A manifest span looks like:

```json
{
  "start": 12.34, "end": 12.71,
  "term": "fuck", "severity": "high",
  "source_text": "Fuck!", "confidence": 0.98
}
```

## Wordlist

`config/wordlist.yaml` is a configurable blocklist with per-term severity and an
`allowlist` for whole-word exceptions. Matching is whole-word / whole-phrase and
case/punctuation-insensitive — never substrings, so "class" and "assassin" are
safe (the Scunthorpe problem).

## Design notes

- **Injected ASR seam.** `pipeline.build_manifest` depends on the `Transcriber`
  protocol, not WhisperX directly. WhisperX is imported lazily, so the core and
  its tests run without torch.
- **Pure core.** Normalization (`text.py`) and matching (`wordlist.py`) are pure
  functions, unit-tested without audio or models.
- **Manifest is audio-agnostic.** Detection produces an edit list; rendering is
  a later, separate concern.

## Not yet built

- Stage 5: span post-processing. Intended behavior: **no padding.** A slight
  negative inset (shrinkage) so the onset of the first consonant and the tail of
  the last stay audible (hear the "f" and "k" of "fuck"). Snap each voice<->bleep
  transition to a zero-crossing (or a ~2-3ms micro-fade) to avoid clicks. Merge
  spans that overlap after inset.
- Stage 6: the bleep renderer (1 kHz tone + duck + splice into the original).
- Phonetic safety net for words the ASR mis-transcribes (the main false-negative risk).
