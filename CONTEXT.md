# Podio

The vocabulary for the audio pass that sits between raw per-speaker recordings
and the NLE timeline for a *Yelling at Robots* episode. Prep cleans each take,
brings it to delivery loudness and censors it. Syncing and cutting belong to the
NLE, which does not set loudness again.

## Language

**Episode**:
One published show, recorded as a set of takes captured simultaneously.
_Avoid_: show, session

**Take**:
One speaker's recording of one episode, as a single file. Takes within an
episode are independently recorded and may differ in level, noise floor, and
duration.
_Avoid_: track, file, source, speaker

**Bumper**:
A short piece of audio recorded straight to disk for an episode — an intro, an
outro, a transition. Deliberately not a take: podio captures it from a
microphone rather than cleaning a recording someone else made. Recorded raw, at
the working rate; prepping it without the bleep brings it to delivery loudness
beside the takes.
_Avoid_: sting, ident, jingle, clip, intro

**Capture Device**:
A microphone, as ffmpeg addresses it — always through OpenAL, on every platform,
because it is the one capture path that does not drop buffers. Identified by
name; the numbers `podio devices` prints are positions in a listing that changes
as devices come and go, so a name is what can be written down.
_Avoid_: input, source, mic, interface, channel

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

**Prep**:
The whole pass on one source file: clean, level to delivery loudness, detect,
bleep, and put the audio back in the source's container. Every other step is an
intermediate of it, and runs on its own only to debug.
_Avoid_: process, run, finish, pipeline

**Cleaned Take**:
The output of the chain for one take, brought to delivery loudness but not yet
censored. An intermediate.
_Avoid_: clean track, processed file, mixed

**Censored Take**:
A cleaned take with every span in its manifest replaced by the tone. An
intermediate: prep puts it back into the source's container.
_Avoid_: final, master, bleeped file

**Prepped Take**:
What prep writes: `NAME_prepped.mp4` or `NAME_prepped.wav`, the same kind of
file as the source. The deliverable — the file that goes to the NLE timeline.
_Avoid_: final, master, output

**Stage**:
One named step in the pass, carrying its own parameters. Most transform audio
and can be switched off without disturbing the others. Those that write or read
a manifest cannot: switching off the stage that writes one leaves whatever reads
it with nothing — or, worse, with a stale one left over from a previous run.
_Avoid_: step, filter, effect, phase

**Chain**:
The ordered sequence of enabled stages applied to a take.
_Avoid_: pipeline, graph, filter string

**Delivery Loudness**:
-16 LUFS integrated under -1 dBTP: what every take is brought to, by one
constant gain and a true-peak limiter, rendered again until it settles. Fixed,
not configurable.
_Avoid_: target loudness, LUFS target, working level, normalization

**Working Rate**:
48 kHz — the sample rate the chain runs at, and so the rate every cleaned and
censored take is written at. Fixed, not configurable: it is what video work
expects and the only rate `rnnoise` runs at. Every take is brought to it once,
before the chain.
_Avoid_: sample rate, target rate, project rate

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
edited, and rendered with `podio debug bleep` without re-running detection.
Prep throws it away unless asked to keep its intermediates.
_Avoid_: EDL, censor list, cuts, spans file

**Transcript**:
Every word detection heard in a take, with its timing and confidence. The
auditable record of why the manifest says what it says, and the place to look
when a word was missed.
_Avoid_: captions, subtitles, ASR output

**Tone Level**:
The level of the tone that replaces a span: -19 dBFS RMS, three dB under
delivery loudness, so its peak sits at -16 dBFS. A censored passage is meant to
be unmistakable, not the loudest thing in the episode.
_Avoid_: bleep volume, amplitude, tone gain

**Analysis Sidecar**:
The per-take record of what prep measured and what every auto value resolved
to, kept among the intermediates. A record of a run, never an input to one.
_Avoid_: cache, lockfile, state
