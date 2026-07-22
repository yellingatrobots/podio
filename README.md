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

Detected spans are post-processed (Stage 5) before the manifest is written.
`--inset SECONDS` (default 0.03) sets how far each span edge is shrunk inward;
`--inset 0` disables the shrink.

Each `manifest` run writes two files: the manifest (spans to bleep) and a
sibling `*.transcript.json` (the full word list with timestamps) — the lean
edit-list and the auditable record, respectively. `out.json` yields
`out.transcript.json`.

A manifest span looks like:

```json
{
  "start": 12.34, "end": 12.71,
  "term": "fuck",
  "source_text": "Fuck!", "confidence": 0.98
}
```

## Wordlist

`config/wordlist.yaml` is a configurable blocklist with an `allowlist` for
whole-word exceptions. Matching is whole-word / whole-phrase and
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

## Span post-processing (Stage 5)

`postprocess.py` transforms the raw `find_spans` output into a render-ready edit
list — a pure function over `CensorSpan`s, no audio or models:

- **No padding, a negative inset.** Each span is shrunk inward by `inset` seconds
  on each edge so the onset of the first consonant and the tail of the last stay
  audible (hear the "f" and "k" of "fuck"). The inset is a parameter.
- Spans that collapse to <= 0 width after inset are dropped.
- Spans that still overlap after inset are merged into one; the merged span joins
  both words' `term` and `source_text` and takes the minimum `confidence`.

## Not yet built

- Stage 6: the bleep renderer (1 kHz tone + duck + splice into the original).
- Phonetic safety net for words the ASR mis-transcribes (the main false-negative risk).

## License

MIT — see [LICENSE](LICENSE). Permissive; requires that the copyright and
permission notice be preserved in copies (attribution).
