# Repo tasks: install, test, and a one-shot censor demo. Recipes run in this
# directory, so episodes are worked on with `podio` itself, not through here.
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

# For a machine with no nix config of its own. Personal machines get podio
# from the home-manager module in ~/etc; a profile copy would shadow that one.
# To just try it, no install needed:
#   nix run github:yellingatrobots/podio -- devices
#
# Put `podio` on your PATH imperatively
install:
    nix profile install .

# Run the tests
test:
    pytest -q

# e.g. `just censor test_audio/profanity.m4a`. Fast model by default.
#
# One-shot: detect + render so you can just hear it
censor audio out="censored.wav" model="base.en":
    #!/usr/bin/env bash
    set -euo pipefail
    tmp="$(mktemp -d)"
    {{podio}} detect "{{audio}}" --out "$tmp/manifest.json" --model {{model}}
    {{podio}} bleep "{{audio}}" "$tmp/manifest.json" --out "{{out}}"
    echo "wrote {{out}}  (play it: afplay {{out}})"
