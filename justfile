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
    python -m bleep.cli normalize {{audio}} --out {{out}}

# Transcribe + detect profanity -> write a censor manifest (JSON).
# Requires `just setup-asr` first (uses the venv for the ML deps).
manifest audio out="manifest.json" wordlist="config/wordlist.yaml":
    PYTHONPATH=src .venv/bin/python -m bleep.cli manifest {{audio}} --out {{out}} --wordlist {{wordlist}}

# Render censored audio from a manifest (1 kHz bleep tone). No ASR deps needed.
bleep audio manifest out="censored.wav":
    python -m bleep.cli bleep {{audio}} {{manifest}} --out {{out}}
