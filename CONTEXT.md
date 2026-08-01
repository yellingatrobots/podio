# Podio

The vocabulary for the audio pass that sits between raw per-speaker recordings
and the NLE timeline for a *Yelling at Robots* episode. The pass cleans each
take and censors it. Syncing, mixing and final distribution loudness belong to
the NLE.

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

**Prepped Take**:
The audio output of the chain for one take: denoised, leveled, and gain-matched,
but not yet censored. An intermediate — it exists so a censored take can be
re-rendered without re-running the chain.
_Avoid_: clean track, processed file, mixed, output

**Censored Take**:
A prepped take with every span in its manifest replaced by the tone. The
deliverable — the file that goes to the NLE timeline.
_Avoid_: final, master, bleeped file

**Stage**:
One named step in the pass, carrying its own parameters. Most transform audio
and can be switched off without disturbing the others. Those that write or read
a manifest cannot: switching off the stage that writes one leaves whatever reads
it with nothing — or, worse, with a stale one left over from a previous run.
_Avoid_: step, filter, effect, phase

**Chain**:
The ordered sequence of enabled stages applied to a take.
_Avoid_: pipeline, graph, filter string

**Working Level**:
The integrated loudness every prepped take is brought to. Deliberately not a
distribution loudness — it exists so takes sit at a common level with headroom
for the NLE to mix and finalise.
_Avoid_: target loudness, LUFS target, normalization target

**Working Rate**:
The sample rate the chain runs at, and so the rate every prepped and censored
take is written at. A take arriving at another rate is resampled to it once,
before the chain; a take already at it is passed through untouched. Distinct
from the **working level**, which is about loudness rather than rate.
_Avoid_: sample rate, target rate, project rate

**Gain Match**:
Bringing a take to the working level by a single constant gain, computed from
the loudness measured at the end of that take's chain. Changes level only;
never dynamics.
_Avoid_: normalize, level, loudnorm

**Peak Ceiling**:
The true-peak limit a take may not exceed. When gain match would breach it, the
tool reduces the gain and says so rather than clipping silently.
_Avoid_: headroom, limit, max peak

**Noise Floor**:
The level of a take during the passages where nobody is speaking, estimated as a
low percentile of one-second windows. Deliberately not the quietest moment in the
take — an edit or a dropout is silence, not room tone.
_Avoid_: silence, background, noise level

**Auto Value**:
A stage parameter expressed relative to something measured (`"floor+12"`)
rather than as a fixed number. How a chain adapts to conditions without being
re-tuned by hand. The noise floor is the only reference there is.
_Avoid_: dynamic, adaptive, computed

**Wordlist**:
The configurable set of terms to censor, with an allowlist of whole words that
must never be censored whatever else matches. Matching is whole-word or
whole-phrase and case- and punctuation-insensitive, never substrings.
_Avoid_: blocklist, dictionary, banned words, filter

**Span**:
One region of a take to be censored — a start and an end, with the term that
matched, the surrounding text, and the confidence it was heard with. Timed
against the take, so it survives being reviewed and edited by hand.
_Avoid_: region, segment, cut, mute, hit

**Manifest**:
The spans for one take, as a file. An edit list, not audio — it can be read,
edited, and re-rendered without re-running detection. It persists between runs,
which is what makes hand-editing possible and staleness possible with it.
_Avoid_: EDL, censor list, cuts, spans file

**Transcript**:
Every word detection heard in a take, with its timing and confidence. The
auditable record of why the manifest says what it says, and the place to look
when a word was missed.
_Avoid_: captions, subtitles, ASR output

**Tone Level**:
The level of the tone that replaces a span, expressed relative to the working
level so it tracks it. A censored passage is meant to be unmistakable, not the
loudest thing in the episode.
_Avoid_: bleep volume, amplitude, tone gain

**Analysis Sidecar**:
The per-episode record of what a run measured and what every auto value resolved
to. A record of a run, never an input to one.
_Avoid_: cache, lockfile, state
