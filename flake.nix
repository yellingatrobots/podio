{
  description = "Offline AI-driven profanity bleeping pipeline";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs = { self, nixpkgs, flake-utils }:
    flake-utils.lib.eachDefaultSystem (system:
      let
        pkgs = import nixpkgs { inherit system; };

        # Lightweight interpreter for the pure core + fast tests.
        # The heavy ASR stack (WhisperX/torch) is installed on demand into a
        # uv venv via `just setup-asr`, since it is not cleanly packaged here.
        python = pkgs.python312.withPackages (ps: with ps; [
          pytest
        ]);
      in {
        devShells.default = pkgs.mkShell {
          packages = [
            python
            pkgs.ffmpeg   # audio decode / normalize
            pkgs.just     # task runner
            pkgs.uv       # installs the ASR extras
          ];

          shellHook = ''
            export PYTHONPATH="$PWD/src:$PYTHONPATH"
            echo "bleep-pipeline dev shell — run 'just' to see tasks"
          '';
        };
      });
}
