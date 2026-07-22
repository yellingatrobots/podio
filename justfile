# bleep-pipeline operations layer.
# Run everything inside the nix dev shell:  nix develop -c just <task>

# Show available tasks
default:
    @just --list

# Run the fast unit tests (pure logic — no ML deps required)
test:
    pytest -q

# Install the heavy ASR stack (WhisperX + torch) into a local venv.
# Only needed to run real transcription; tests do not require it.
setup-asr:
    uv venv .venv
    uv pip install --python .venv whisperx pyyaml

# Debug helper: normalize an audio file to 16kHz mono wav
normalize audio out="normalized.wav":
    python -m bleep.cli normalize "{{audio}}" --out "{{out}}"

# Transcribe + detect profanity -> write a censor manifest (JSON).
# Requires `just setup-asr` first (uses the venv for the ML deps).
# `model` defaults to base.en (fast); pass model=large-v3 for higher accuracy.
# `min_confidence` drops shaky detections (e.g. min_confidence=0.5); default keeps all.
manifest audio out="manifest.json" model="base.en" min_confidence="0" wordlist="config/wordlist.yaml":
    PYTHONPATH=src .venv/bin/python -m bleep.cli manifest "{{audio}}" --out "{{out}}" --wordlist "{{wordlist}}" --model {{model}} --min-confidence {{min_confidence}}

# Render censored audio from a manifest (1 kHz bleep tone). No ASR deps needed.
bleep audio manifest out="censored.wav":
    python -m bleep.cli bleep "{{audio}}" "{{manifest}}" --out "{{out}}"

# One-shot: detect + render so you can just hear it. Fast model by default.
# Requires `just setup-asr` first.  e.g. `just censor test_audio/profanity.m4a`
censor audio out="censored.wav" model="base.en":
    #!/usr/bin/env bash
    set -euo pipefail
    tmp="$(mktemp -d)"
    PYTHONPATH=src .venv/bin/python -m bleep.cli manifest "{{audio}}" --out "$tmp/manifest.json" --model {{model}}
    python -m bleep.cli bleep "{{audio}}" "$tmp/manifest.json" --out "{{out}}"
    echo "wrote {{out}}  (play it: afplay {{out}})"
