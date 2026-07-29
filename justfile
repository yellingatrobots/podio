# podio operations layer.
# Run everything inside the nix dev shell:  nix develop -c just <task>
#
# nix supplies ffmpeg, just and uv; uv supplies the interpreter and every
# Python dependency. There is one environment — `uv run` is always the way in.

# Show available tasks
default:
    @just --list

# Install/refresh the environment from the lock (first run pulls the ASR stack)
sync:
    uv sync

# Put `podio` on your PATH, so it can be run from an episode directory.
# A symlink, not a copy: the entry point's shebang already points at this
# repo's .venv, and the install is editable, so edits here take effect at once.
install bindir="~/.local/bin": sync
    #!/usr/bin/env bash
    set -euo pipefail
    dir="$(eval echo {{bindir}})"
    mkdir -p "$dir"
    ln -sf "$(pwd)/.venv/bin/podio" "$dir/podio"
    echo "linked $dir/podio -> $(pwd)/.venv/bin/podio"
    command -v podio >/dev/null || echo "warning: $dir is not on your PATH"

# Run the tests
test:
    uv run pytest -q

# Clean an episode's takes into prepped takes. Run from the episode directory.
clean *args:
    uv run podio clean {{args}}

# Debug helper: normalize an audio file to 16kHz mono wav
normalize audio out="normalized.wav":
    uv run podio normalize "{{audio}}" --out "{{out}}"

# Transcribe + detect profanity -> write a censor manifest (JSON).
# `model` defaults to base.en (fast); pass model=large-v3 for higher accuracy.
# `min_confidence` drops shaky detections (e.g. min_confidence=0.5); default keeps all.
detect audio out="manifest.json" model="base.en" min_confidence="0" wordlist="config/wordlist.toml":
    uv run podio detect "{{audio}}" --out "{{out}}" --wordlist "{{wordlist}}" --model {{model}} --min-confidence {{min_confidence}}

# Render a censored copy from a manifest (1 kHz bleep tone).
# Output format follows `out`'s extension: .wav writes audio directly; .mp4/.m4a
# remux the bleeped audio over the source (video copied through untouched).
bleep audio manifest out="censored.wav":
    uv run podio bleep "{{audio}}" "{{manifest}}" --out "{{out}}"

# One-shot: detect + render so you can just hear it. Fast model by default.
# e.g. `just censor test_audio/profanity.m4a`
censor audio out="censored.wav" model="base.en":
    #!/usr/bin/env bash
    set -euo pipefail
    tmp="$(mktemp -d)"
    uv run podio detect "{{audio}}" --out "$tmp/manifest.json" --model {{model}}
    uv run podio bleep "{{audio}}" "$tmp/manifest.json" --out "{{out}}"
    echo "wrote {{out}}  (play it: afplay {{out}})"
