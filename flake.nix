{
  description = "podio — clean and censor an episode's takes for the NLE";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs = { self, nixpkgs, flake-utils }:
    flake-utils.lib.eachDefaultSystem (system:
      let
        pkgs = import nixpkgs {
          inherit system;
          overlays = [ optunaFix ];
        };

        # whisperx pulls optuna in through pyannote-pipeline, and optuna 4.9.0
        # fails three of its own tests: two assert on logging handlers that
        # pytest's live-logging installs, one on a visualization warning count.
        # Neither touches anything podio calls.
        optunaFix = final: prev: {
          pythonPackagesExtensions = prev.pythonPackagesExtensions ++ [
            (pyfinal: pyprev: {
              optuna = pyprev.optuna.overridePythonAttrs (old: {
                disabledTests = (old.disabledTests or [ ]) ++ [
                  "test_default_handler"
                  "test_propagation"
                  "test_filter_inf_trials_message"
                ];
              });
            })
          ];
        };

        # Shared by the package and the dev shell, so both resolve one dep set.
        python = pkgs.python3;

        # ffmpeg-full carries the OpenAL capture device, and OpenAL is the only
        # input podio records through. avfoundation, the obvious macOS
        # alternative, loses 11-17% of what it captures — see capture.py.
        #
        # The version follows whatever nixpkgs the consumer supplies. podio
        # scrapes ffmpeg's stderr, so it is a check input below: the end-to-end
        # parser tests run against this exact binary at build time.
        ffmpeg = pkgs.ffmpeg-full;

        podio = python.pkgs.buildPythonApplication {
          pname = "podio";
          version = "0.1.0";
          pyproject = true;
          src = ./.;

          build-system = [ python.pkgs.hatchling ];
          dependencies = with python.pkgs; [ pydantic whisperx ];

          # tests/test_end_to_end.py skips itself when ffmpeg is off PATH, so
          # dropping ffmpeg here turns the parser check into a no-op.
          nativeCheckInputs = [ python.pkgs.pytestCheckHook ffmpeg ];

          # Baked in at build time, so it cannot go stale the way a generated
          # wrapper does after `nix flake update`.
          makeWrapperArgs = [ "--set" "PODIO_FFMPEG" "${ffmpeg}/bin/ffmpeg" ];

          meta = {
            description = "Clean and censor an episode's takes into NLE-ready audio";
            mainProgram = "podio";
          };
        };
      in {
        packages.default = podio;

        # `inputsFrom` gives the shell podio's own dependency closure, so the
        # shell and the installed tool cannot disagree. podio itself is absent:
        # PYTHONPATH and the justfile's `python -m podio` run the working tree.
        #
        # uv.lock still describes a `uv sync` for anyone without nix — set
        # $PODIO to "uv run podio". Nothing here exercises that path.
        devShells.default = pkgs.mkShell {
          inputsFrom = [ podio ];
          packages = [
            ffmpeg
            pkgs.just
            python.pkgs.pytest
          ];

          shellHook = ''
            export PYTHONPATH="$PWD/src''${PYTHONPATH:+:$PYTHONPATH}"
            echo "podio dev shell — run 'just' to see tasks"
          '';
        };
      });
}
