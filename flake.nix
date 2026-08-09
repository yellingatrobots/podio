{
  description = "podio — clean and censor an episode's takes for the NLE";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs = { self, nixpkgs, flake-utils }:
    flake-utils.lib.eachDefaultSystem (system:
      let
        pkgs = import nixpkgs { inherit system; };
      in {
        # The seam: nix supplies the system binaries uv cannot, uv supplies the
        # Python stack nix packages badly. No python here on purpose — a second
        # interpreter is how you end up unsure which one you are running.
        #
        # ffmpeg is the one that must be pinned: podio scrapes its
        # human-readable stderr for loudness and per-window levels, so a
        # formatting change upstream breaks parsing rather than the build.
        #
        # ffmpeg-full rather than ffmpeg, for one reason: it is the build that
        # carries the OpenAL capture device, and OpenAL is the only way podio
        # records. The obvious alternative on macOS, avfoundation, is in every
        # build and loses 11-17% of the audio it captures — see the comment at
        # the top of src/podio/capture.py.
        devShells.default = pkgs.mkShell {
          packages = [
            pkgs.ffmpeg-full   # measurement, filtering, decode/mux, capture
            pkgs.just     # task runner
            pkgs.uv       # owns the Python interpreter and every Python dep
          ];

          shellHook = ''
            echo "podio dev shell — run 'just' to see tasks"
          '';
        };
      });
}
