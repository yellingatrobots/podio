# Takes leave podio at delivery loudness

Supersedes 0001 and 0003. Each take is now brought to -16 LUFS integrated, under
-1 dBTP, by `podio prep`. The NLE syncs and cuts, but it does not set loudness again,
and nothing runs after it. The gain-and-limiter loop that `podio master` used on the
mixdown now runs on each take, and `podio master` is gone with its feed MP3.

0001 ruled this out because two takes at -16 sum louder than -16. That holds only
where the speakers overlap. Integrated loudness is gated, so each take is measured
while its speaker talks, and where speakers alternate the mix sits at about the
level of each take. This show has little crosstalk, so the overshoot is short and
local. A second leveling pass on the mix would cost an export, an import and a
re-encode for every episode. That is not worth it here.

`prep` takes one source file and gives back the same kind of file: an mp4 with
its picture copied and its audio replaced (AAC, 192 kbps), or a 24-bit 48 kHz wav.
A wav with the same name beside a video is used as its audio. All the
intermediates live in a temporary directory. The steps stay available on their
own under `podio debug`.

## Consequences

Crosstalk, laughter over speech and other overlaps play louder than -16 LUFS in
the mix. If that becomes audible, the remedy is to measure the exported mix, not
to lower the takes. The tone moves with the target: -19 dBFS RMS, 3 dB under
delivery loudness, so its peak sits at -16 dBFS. The NLE encodes the AAC again on
export. At 192 kbps that second generation is inaudible on speech. The review loop
for hand-edited manifests (`--review`, `--redetect`) and audition ranges are
removed. A manifest can still be edited and rendered with `podio debug bleep`.
