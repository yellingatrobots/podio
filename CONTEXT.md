# Podcast Audio

The vocabulary for the audio cleanup pass that sits between raw per-speaker
recordings and the NLE timeline for a *Yelling at Robots* episode. This context
covers only the cleanup pass; final loudness and the mixdown belong to the NLE.

## Language

**Episode**:
One published show, recorded as a set of takes captured simultaneously.
_Avoid_: show, session

**Take**:
One speaker's recording of one episode, as a single file. Takes within an
episode are independently recorded and may differ in level, noise floor, and
duration.
_Avoid_: track, file, source, speaker

**Rig**:
A speaker's stable recording setup — the microphone and its consistent tonal
consequences. Belongs to the speaker across episodes, and is deliberately
distinct from the conditions a take was recorded under.
_Avoid_: profile, preset, setup

**Conditions**:
Everything about a take that varies between episodes rather than persisting with
the rig — room tone, a fan, a hotel room on the road. Measured per take, never
assumed.
_Avoid_: environment, noise, room

**Clean Track**:
The audio-only output of the cleanup pass for one take: denoised, leveled, and
gain-matched, ready to be placed on the NLE timeline.
_Avoid_: processed file, podcast file, output

**Stage**:
One named, individually toggleable step in the cleanup pass, carrying its own
parameters. Every stage can be switched off without disturbing the others.
_Avoid_: step, filter, effect

**Chain**:
The ordered sequence of enabled stages applied to a take.
_Avoid_: pipeline, graph, filter string

**Working Level**:
The integrated loudness every clean track is brought to. Deliberately not a
distribution loudness — it exists so takes sit at a common level with headroom
for the NLE to mix and finalise.
_Avoid_: target loudness, LUFS target, normalization target

**Gain Match**:
Bringing a take to the working level by a single constant gain, computed from
the loudness measured at the end of that take's chain. Changes level only;
never dynamics.
_Avoid_: normalize, level, loudnorm

**Peak Ceiling**:
The true-peak limit a clean track may not exceed. When gain match would breach
it, the tool reduces the gain and says so rather than clipping silently.
_Avoid_: headroom, limit, max peak

**Noise Floor**:
The level of a take during the passages where nobody is speaking, estimated as a
low percentile of one-second windows. Deliberately not the quietest moment in the
take — an edit or a dropout is silence, not room tone.
_Avoid_: silence, background, noise level

**Auto Value**:
A stage parameter expressed relative to something measured about the take
(`"floor+12"`) rather than as a fixed number. How a chain adapts to conditions
without being re-tuned by hand.
_Avoid_: dynamic, adaptive, computed

**Analysis Sidecar**:
The per-episode record of what a run measured and what every auto value resolved
to. A record of a run, never an input to one.
_Avoid_: cache, lockfile, state
