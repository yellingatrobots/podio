# podio operations layer.
# Run everything inside the nix dev shell:  nix develop -c just <task>
#
# nix supplies ffmpeg, just, the interpreter and every Python dependency —
# the same ones the installed tool is built from.

# How podio is invoked. The default runs this working tree against the dev
# shell's dependencies. Without nix:  PODIO="uv run podio" just <task>
podio := env_var_or_default("PODIO", "python -m podio")

# Show available tasks
default:
    @just --list

# Put `podio` on your PATH imperatively, for a machine with no nix config of
# its own. Personal machines get it from the home-manager module in ~/etc; a
# profile copy would shadow that one. To just try it, no install needed:
#   nix run github:yellingatrobots/podio -- devices
install:
    nix profile install .

# Run the tests
test:
    pytest -q

# Clean an episode's takes into prepped takes. Run from the episode directory.
clean *args:
    {{podio}} clean {{args}}

# List the microphones a bumper can be recorded from.
devices:
    {{podio}} devices

# Record a bumper (intro/outro/transition). `device` takes a number from
# `just devices`; omit it for the system default. Press q to stop.
bumper out="bumper.wav" device="":
    {{podio}} bumper "{{out}}" {{ if device != "" { "--device " + device } else { "" } }}

# Debug helper: normalize an audio file to 16kHz mono wav
normalize audio out="normalized.wav":
    {{podio}} normalize "{{audio}}" --out "{{out}}"

# Transcribe + detect profanity -> write a censor manifest (JSON).
# `model` defaults to base.en (fast); pass model=large-v3 for higher accuracy.
# `min_confidence` drops shaky detections (e.g. min_confidence=0.5); default keeps all.
# `wordlist` overrides the one shipped with the tool.
detect audio out="manifest.json" model="base.en" min_confidence="0" wordlist="":
    {{podio}} detect "{{audio}}" --out "{{out}}" {{ if wordlist != "" { "--wordlist " + wordlist } else { "" } }} --model {{model}} --min-confidence {{min_confidence}}

# Render a censored copy from a manifest (1 kHz bleep tone).
# Output format follows `out`'s extension: .wav writes 24-bit audio directly;
# anything else remuxes over the source, video copied through untouched. .mov
# and .mkv carry the audio as 24-bit PCM; .mp4/.m4a can only encode it to AAC.
bleep audio manifest out="censored.wav":
    {{podio}} bleep "{{audio}}" "{{manifest}}" --out "{{out}}"

# One-shot: detect + render so you can just hear it. Fast model by default.
# e.g. `just censor test_audio/profanity.m4a`
censor audio out="censored.wav" model="base.en":
    #!/usr/bin/env bash
    set -euo pipefail
    tmp="$(mktemp -d)"
    {{podio}} detect "{{audio}}" --out "$tmp/manifest.json" --model {{model}}
    {{podio}} bleep "{{audio}}" "$tmp/manifest.json" --out "{{out}}"
    echo "wrote {{out}}  (play it: afplay {{out}})"
