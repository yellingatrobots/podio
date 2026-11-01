{
  description = "podio — clean and censor an episode's takes for the NLE";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";

    pyproject-nix = {
      url = "github:pyproject-nix/pyproject.nix";
      inputs.nixpkgs.follows = "nixpkgs";
    };
    uv2nix = {
      url = "github:pyproject-nix/uv2nix";
      inputs.pyproject-nix.follows = "pyproject-nix";
      inputs.nixpkgs.follows = "nixpkgs";
    };
    pyproject-build-systems = {
      url = "github:pyproject-nix/build-system-pkgs";
      inputs.pyproject-nix.follows = "pyproject-nix";
      inputs.uv2nix.follows = "uv2nix";
      inputs.nixpkgs.follows = "nixpkgs";
    };
  };

  outputs = { self, nixpkgs, flake-utils, pyproject-nix, uv2nix, pyproject-build-systems }:
    # The platforms uv.lock resolves for; see [tool.uv] in pyproject.toml.
    flake-utils.lib.eachSystem [ "aarch64-darwin" "aarch64-linux" "x86_64-linux" ] (system:
      let
        pkgs = nixpkgs.legacyPackages.${system};
        inherit (nixpkgs) lib;

        # uv.lock sets every Python package version; nixpkgs supplies only the
        # interpreter, ffmpeg and the tools. uv reads the same .python-version.
        python = pkgs."python${lib.replaceStrings [ "." ] [ "" ] (lib.fileContents ./.python-version)}";

        workspace = uv2nix.lib.workspace.loadWorkspace { workspaceRoot = ./.; };

        # Linux wheels go through autoPatchelf; these are the ones it cannot
        # satisfy by itself.
        fixups = final: prev:
          let
            # libtorch ships inside the torch wheel, not in a lib/ directory
            # autoPatchelf searches.
            linkLibtorch = old: lib.optionalAttrs pkgs.stdenv.isLinux {
              preFixup = (old.preFixup or "") + ''
                addAutoPatchelfSearchPath ${final.torch}/${python.sitePackages}/torch/lib
              '';
            };
          in {
            # Published only as an sdist, with no build system in the lock.
            antlr4-python3-runtime = prev.antlr4-python3-runtime.overrideAttrs (old: {
              nativeBuildInputs = old.nativeBuildInputs ++ final.resolveBuildSystem { setuptools = [ ]; };
            });
            # whisperx requires triton on x86_64 Linux. libcuda comes from a GPU
            # driver, and these builds run on the CPU.
            triton = prev.triton.overrideAttrs (old: {
              autoPatchelfIgnoreMissingDeps = [ "libcuda.so.1" ];
            });
            # pyannote requires it, but podio never decodes through it; see
            # _without_torchcodec_warning in transcribe.py.
            torchcodec = prev.torchcodec.overrideAttrs (old: {
              autoPatchelfIgnoreMissingDeps = true;
            });
            # Its FFmpeg and sox backends load only on demand, and podio uses neither.
            torchaudio = prev.torchaudio.overrideAttrs (old: linkLibtorch old // {
              autoPatchelfIgnoreMissingDeps = [ "libav*" "libsw*" "libsox.so" ];
            });
            torchvision = prev.torchvision.overrideAttrs linkLibtorch;
          };

        pythonSet = (pkgs.callPackage pyproject-nix.build.packages { inherit python; }).overrideScope
          (lib.composeManyExtensions [
            pyproject-build-systems.overlays.default
            (workspace.mkPyprojectOverlay { sourcePreference = "wheel"; })
            fixups
          ]);

        # ffmpeg-full carries the OpenAL capture device, and OpenAL is the only
        # input podio records through. avfoundation, the obvious macOS
        # alternative, loses 11-17% of what it captures — see capture.py.
        #
        # The version follows whatever nixpkgs the consumer supplies. podio
        # scrapes ffmpeg's stderr, so the pytest check below runs the
        # end-to-end parser tests against this exact binary.
        ffmpeg = pkgs.ffmpeg-full;

        inherit (pkgs.callPackages pyproject-nix.build.util { }) mkApplication;

        # The version is dynamic, so uv.lock has none; read it where hatch and
        # --version do.
        version = builtins.head (builtins.match ''.*__version__ = "([^"]+)".*''
          (builtins.readFile ./src/podio/__init__.py));

        podio = (mkApplication {
          venv = pythonSet.mkVirtualEnv "podio-env" workspace.deps.default;
          package = pythonSet.podio;
          inherit version;
        }).overrideAttrs (old: {
          nativeBuildInputs = old.nativeBuildInputs ++ [ pkgs.makeWrapper ];
          # Baked in at build time, so it cannot go stale the way a generated
          # wrapper does after `nix flake update`.
          postInstall = ''
            wrapProgram $out/bin/podio --set PODIO_FFMPEG ${ffmpeg}/bin/ffmpeg
          '';
          meta = old.meta // {
            description = "Clean and censor an episode's takes into NLE-ready audio";
            mainProgram = "podio";
          };
        });

        # tests/test_end_to_end.py skips itself when ffmpeg is off PATH, so
        # dropping ffmpeg here turns the parser check into a no-op.
        pytest = pkgs.stdenv.mkDerivation {
          name = "podio-pytest";
          src = ./.;
          nativeBuildInputs = [ (pythonSet.mkVirtualEnv "podio-test-env" workspace.deps.all) ffmpeg ];
          dontConfigure = true;
          buildPhase = ''
            export HOME=$TMPDIR
            pytest -q -p no:cacheprovider
          '';
          installPhase = "touch $out";
        };

        # podio is installed editable from $REPO_ROOT/src, so `podio` runs the
        # working tree. uv is here to edit uv.lock, never to make a .venv.
        devVenv = (pythonSet.overrideScope (lib.composeManyExtensions [
          (workspace.mkEditablePyprojectOverlay { root = "$REPO_ROOT"; })
          # hatchling builds an editable install only with editables present.
          (final: prev: {
            podio = prev.podio.overrideAttrs (old: {
              nativeBuildInputs = old.nativeBuildInputs ++ final.resolveBuildSystem { editables = [ ]; };
            });
          })
        ])).mkVirtualEnv "podio-dev-env" workspace.deps.all;
      in {
        packages.default = podio;
        checks.default = pytest;

        devShells.default = pkgs.mkShell {
          packages = [ devVenv pkgs.uv ffmpeg pkgs.just ];
          env = {
            UV_NO_SYNC = "1";
            UV_PYTHON = "${devVenv}/bin/python";
            # `uv run` here uses the shell's venv, never a .venv from `uv sync`.
            UV_PROJECT_ENVIRONMENT = "${devVenv}";
            UV_PYTHON_DOWNLOADS = "never";
          };
          shellHook = ''
            unset PYTHONPATH
            export REPO_ROOT=$(git rev-parse --show-toplevel)
            echo "podio dev shell — run 'just' to see tasks"
          '';
        };
      });
}
