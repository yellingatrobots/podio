# podio masters the NLE's mixdown

Partly supersedes 0001, whose consequences ruled a distribution master out of this
repo. Nothing after the NLE was setting delivery loudness, so `podio master` now does:
it reads the NLE's exported mp4 and writes `STEM_mastered.mp4` and `STEM_mastered.mp3`
at -16 LUFS integrated, under -1 dBTP — the podcast baseline (Apple Podcasts, AES
TD1008). The rest of 0001 stands: takes are still cleaned at the working level, and
master runs once, on the mix, so nothing is stamped onto takes that are summed later.

Level is one constant gain followed by a limiter, not `loudnorm`, for 0002's reason:
`loudnorm` rides gain whenever the peaks will not fit, and says nothing. A mixdown at
the -24 working level with a 22 dB peak-to-loudness ratio needs about +8 dB, so the
limiter has real work to do, and that work should be one visible stage. alimiter
limits sample peaks only, so it runs at four times the working rate, where samples
land close to the inter-sample peaks. Its ceiling is -1.5 dB, half a dB under the
limit, for the overshoot AAC and MP3 encoding add.

## Consequences

Limiting costs integrated loudness: about two units on raw speech. The master is
rendered again with the shortfall added to the gain until it lands within 0.2 LU,
for at most four passes, each a full render. Both encodes are metered, and a miss of
±1 LU or -1 dBTP is reported but does not fail the run. Dense, heavily limited
material can still overshoot in the MP3. If the limiter is audible on laughs, the
remedy is more compression in the rig or the NLE, not a softer master.
