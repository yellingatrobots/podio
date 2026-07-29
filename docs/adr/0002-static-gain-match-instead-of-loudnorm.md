# Static gain match instead of loudnorm

Takes are brought to the working level by measuring integrated loudness at the end of
the chain and applying one constant `volume` gain. `loudnorm` is not used at all,
which will surprise anyone who has normalised audio with ffmpeg before.

Two reasons. First, `loudnorm` compresses loudness *range* as well as setting level,
and that happens invisibly before the NLE applies its own loudness pass — the result
is compressed twice. A constant gain leaves dynamics for the compressor stage, which
has knobs you can see. Second, `loudnorm` silently abandons `linear=true` and rides
gain over time whenever the source loudness range exceeds the target; measured on
episode 16 it was already doing exactly that, so the previous script's "no pumping"
claim was false in practice.

## Consequences

Clip safety becomes ours to provide, since a constant gain has none. Gain match is
computed post-chain and clamped so the resulting true peak cannot exceed the peak
ceiling; when the clamp bites the tool says so and the remedy is to enable the limiter
stage or lower the working level.
