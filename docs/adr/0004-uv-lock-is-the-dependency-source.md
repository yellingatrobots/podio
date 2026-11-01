# uv.lock is the dependency source for nix and uv

The flake built podio from nixpkgs' Python packages, and `uv.lock` resolved PyPI on
its own. The two disagreed (torch 2.12 on Python 3.14 against torch 2.8 on 3.12), and
nothing tested the uv side. nixpkgs also ran every dependency's own tests: optuna's
and plotly's failed on Asahi, and the overlay that skipped them changed their hashes,
so optuna, plotly, pyannote and whisperx were rebuilt locally after every update.

Now `uv.lock` sets every Python version, and the flake builds from it with uv2nix: the
same wheels, with the same hashes, that `uv sync` installs. nixpkgs supplies the
interpreter, ffmpeg and tools. The lock covers macOS on Apple silicon and Linux on
aarch64 and x86_64, all on Python 3.12, with CPU-only torch on Linux.

The alternative was to keep nixpkgs as the source and export its versions to uv as
constraints, checked by the flake. It kept nixpkgs' source builds, but it needed every
dependency to be in nixpkgs, a regeneration step after each `nix flake update`, uv
users on nixpkgs' Python, and a source build for CUDA torch.

## Consequences

Linux wheels are patched with autoPatchelf. When one needs a library nothing supplies,
the build stops and names it, and the fix is one entry in `fixups` in `flake.nix`.
Dependencies are installed, not tested, so a wheel that loads but fails at runtime on
a 16 KiB-page kernel shows only in podio's own tests: run `nix flake check` on the
Asahi host after a lock change. torchcodec has no 0.7 wheel for aarch64 Linux, so
Asahi gets 0.17, which was built for a newer torch. No CUDA: `--asr-device cuda` needs
a CUDA torch, which these builds do not have.
