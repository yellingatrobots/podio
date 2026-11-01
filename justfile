# Repo tasks: install, test, and a one-shot censor demo. Recipes run in this
# directory, so episodes are worked on with `podio` itself, not through here.
#
# Recipes go through `uv run`, which works the same with or without nix: in
# the nix dev shell it uses the shell's venv, elsewhere it syncs .venv from
# uv.lock. Either way podio runs the working tree.

# How podio is invoked; override with PODIO.
podio := env_var_or_default("PODIO", "uv run podio")

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
    uv run pytest -q

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
