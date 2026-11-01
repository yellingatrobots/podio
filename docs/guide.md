# podio user guide

This guide gives the steps to clean, to censor, and to prepare the takes of one
podcast episode. For the design of the tool and for the development steps, read
the [README](../README.md).

## 1. Words in this guide

| Word          | Meaning                                                               |
| ------------- | --------------------------------------------------------------------- |
| take          | One audio file. It has one speaker and one episode.                   |
| rig           | A file with the stable setup of one speaker. It lists all the stages. |
| stage         | One step in the chain. The gate is an example.                        |
| chain         | The sequence of stages. podio applies the chain to each take.         |
| prepped take  | A take after the chain and after the gain match.                      |
| gain match    | The one change of level that brings a take to the working level.      |
| working level | The loudness that podio gives to each take.                           |
| noise floor   | The level of the quiet parts of a take.                               |
| span          | A start time and an end time. podio puts a tone on this part.         |
| manifest      | A JSON file with all the spans of one take.                           |
| transcript    | A JSON file with each word of a take and its times.                   |
| audition      | A short part of a take. podio writes it to a different file.          |
| bumper        | A recorded introduction, transition, or end message.                  |

## 2. Install podio

You can use podio without an installation. Enter this command:

```sh
nix run github:yellingatrobots/podio -- devices
```

The two dashes divide the options of nix from the options of podio.

To install podio on a machine that has no nix configuration, enter this command
in the directory of the source:

```sh
nix profile install .
```

podio needs the model data of WhisperX. The first detection downloads
approximately 141 MB. Subsequent detections do not use the network.

To show the version, enter this command:

```sh
podio --version
```

## 3. Clean and censor an episode

Do these steps in the directory of the episode.

1. Put one WAV file in the directory for each speaker. Use the name of the
   speaker, for example `ian.wav`.
2. If you will use `podio finish`, put the related video files in the same
   directory. Give each video the name of its take, for example `ian.mp4`.
3. Enter this command:

   ```sh
   podio run --dry-run
   ```

   podio shows an `audio.toml` file and asks you to write it. Answer `y`.
   podio then measures each take, but writes no audio.

4. Examine the noise floor of each take. A value of −75 dB or lower is a quiet
   room. A higher value shows that a machine was in operation. For a higher
   value, refer to section 8.
5. Enter this command:

   ```sh
   podio run
   ```

podio writes these files:

| File                   | Contents                                       |
| ---------------------- | ---------------------------------------------- |
| `NAME_prepped.wav`     | The take after the chain and the gain match.   |
| `NAME_manifest.json`   | The spans to censor. You can change this file. |
| `NAME_transcript.json` | Each word and its times.                       |
| `NAME_censored.wav`    | The prepped take with a tone on each span.     |
| `audio_analysis.toml`  | The measurements of the run.                   |

Import the `NAME_censored.wav` files into the video editor.

## 4. The episode file

`audio.toml` holds the settings that change with each recording. podio writes
the first version of this file for you. This is an example:

```toml
working_level_db = -24.0
peak_ceiling_db  = -2.0

[takes.ian]
file = "ian.wav"
rig  = "ian"

[takes.josh]
file = "josh.wav"
rig  = "josh"
```

| Key                   | Default              | Function                                         |
| --------------------- | -------------------- | ------------------------------------------------ |
| `working_level_db`    | `-24.0`              | The loudness of each prepped take.               |
| `peak_ceiling_db`     | `-2.0`               | The maximum peak level. The gain match obeys it. |
| `takes.NAME.file`     | none                 | The audio file of the take. It is necessary.     |
| `takes.NAME.rig`      | the name of the take | The rig file to use.                             |
| `takes.NAME.limiter`  | `false`              | Decrease the peaks to get the working level.     |
| `censor.enabled`      | `true`               | Censor the episode.                              |
| `censor.wordlist`     | the included list    | A different word list for the episode.           |
| `takes.NAME.censor.*` | the episode values   | The same two keys for one take.                  |

To change a stage for one take, make a table with the name of the stage:

```toml
[takes.ian.afftdn]     # a fan was in operation in this episode
enabled = true
```

Only the stages in the rig are available. podio gives an error message for an
unknown stage.

## 5. Make a rig for your voice

A rig holds the stable setup of one speaker: the microphone, the room, and the
usual tone. The tool includes the rigs `ian` and `josh`.

1. Make a directory for your rigs.
2. Copy an included rig into it. Use the name of the speaker, for example
   `alex.toml`. The included rigs are in `src/podio/data/rigs/` in the source.
3. Change the values. Refer to section 6 for each stage.
4. Give the directory to podio with the `--rigs` option:

   ```sh
   podio run --rigs ./my_rigs
   ```

The directory must have one file for each rig that `audio.toml` names.

A rig lists all the stages, and it sets `enabled = false` for the stages that
are not usually necessary. Keep this rule: a rig holds what does not change,
and `audio.toml` holds what changes with one recording.

## 6. The stages

The chain is always in this sequence:

```
highpass → afftdn → rnnoise → gate → eq → compressor → deesser
```

After the chain, podio does the gain match. If the take sets `limiter = true`,
the limiter operates last.

A stage has an `enabled` key. All levels are in dB. A dB value can also be a
measured value: `"floor+12"` is 12 dB more than the noise floor of that take.
Only `floor` is available as a reference.

### highpass

Removes low-frequency noise: rumble, plosives, and proximity effect.

| Key | Default | Unit |
| --- | ------- | ---- |
| `f` | `80`    | Hz   |

### afftdn

Removes constant noise, for example a fan, an air conditioner, or traffic. Use
this stage before `rnnoise`, because it does not damage the sound of laughter.

| Key              | Default   | Unit                      |
| ---------------- | --------- | ------------------------- |
| `noise_floor_db` | `"floor"` | dB, limited to −80 to −20 |
| `reduction_db`   | `12`      | dB                        |
| `track_noise`    | `true`    | true or false             |

### rnnoise

Removes noise that `afftdn` cannot remove. This stage makes a decision between
voice and other sounds, thus it can damage the sound of laughter.

| Key     | Default | Unit                                          |
| ------- | ------- | --------------------------------------------- |
| `model` | `"lq"`  | `lq` for room noise, `bd` for equipment noise |

This stage needs the RNNoise model files. Set the environment variable
`RNNOISE_MODELS` to the directory of the `.rnnn` files, or give the directory
with the `--models` option. If podio cannot find the file, it gives an error
message with the full path.

### gate

Decreases the level between the phrases.

| Key            | Default      | Unit  |
| -------------- | ------------ | ----- |
| `threshold_db` | `"floor+12"` | dB    |
| `range_db`     | `-40`        | dB    |
| `ratio`        | `6`          | ratio |
| `attack_ms`    | `5`          | ms    |
| `release_ms`   | `250`        | ms    |

### eq

Changes the tone. Each band is one filter. A band has three keys: `f` in Hz,
`width` as a Q value, and `gain_db` in dB. A positive gain increases the band.
A negative gain decreases it.

| Key       | Default |
| --------- | ------- |
| `enabled` | `false` |
| `bands`   | empty   |

This example decreases the low-middle frequencies and increases the high
frequencies. The sound becomes less dull:

```toml
[[stage]]
name = "eq"
enabled = true
bands = [
  { f = 250,   width = 1.2, gain_db = -3 },
  { f = 3500,  width = 0.9, gain_db = 2.5 },
  { f = 10000, width = 0.7, gain_db = 2 },
]
```

In `audio.toml`, write the same stage as a table of the take:

```toml
[takes.josh.eq]
enabled = true
bands = [ { f = 250, width = 1.2, gain_db = -3 } ]
```

### compressor

Decreases the difference between the loud parts and the quiet parts. This is
the only stage that must change the dynamics.

| Key            | Default | Unit  |
| -------------- | ------- | ----- |
| `threshold_db` | `-18`   | dB    |
| `ratio`        | `3`     | ratio |
| `attack_ms`    | `5`     | ms    |
| `release_ms`   | `60`    | ms    |

### deesser

Decreases the sharp "s" sounds. This stage is after the compressor, because the
compressor increases these sounds.

| Key             | Default | Range                                                |
| --------------- | ------- | ---------------------------------------------------- |
| `intensity`     | `0.4`   | 0 to 1. The quantity of the decrease.                |
| `frequency`     | `0.5`   | 0 to 1. 0 is the lowest frequency, 1 is the highest. |
| `max_reduction` | `0.5`   | 0 to 1. The maximum decrease.                        |

If the "s" sounds are sharp, increase `intensity` in steps of 0.1. If the full
voice becomes dull, do not increase `intensity` more. Increase `frequency` to
0.55 or 0.60, because then the stage examines a higher band.

## 7. Censor the words

`podio run` censors each take after it cleans it. To censor a file that is not
part of an episode, use the two commands:

```sh
podio detect ian.wav --out ian_manifest.json
podio bleep ian.wav ian_manifest.json --out ian_censored.wav
```

`podio detect` writes the manifest and the transcript. It writes no audio.
`podio bleep` puts a tone on each span of the manifest.

A span in the manifest has this form:

```json
{
  "start": 12.34,
  "end": 12.71,
  "term": "fuck",
  "source_text": "Fuck!",
  "confidence": 0.98
}
```

To examine the manifests before podio puts the tones on the audio, use
`podio run --review`.

To change a manifest, do these steps:

1. Change the times, or remove a span, in `NAME_manifest.json`.
2. Enter this command:

   ```sh
   podio bleep NAME_prepped.wav NAME_manifest.json --out NAME_censored.wav
   ```

podio stops if you start `podio run` again after a change of the manifest. It
does not remove your changes. To remove your changes and detect again, use the
`--redetect` option.

### The word list

The included word list is `src/podio/data/wordlist.toml`. It has the terms and
an `allowlist` of words that podio must not censor.

podio finds a full word or a full phrase. It ignores the case and the
punctuation. It does not find a part of a word, thus the words "class",
"assassin", and "cockpit" are safe.

To use a different list, give the file in `audio.toml`, or use the `--wordlist`
option.

### The tone

The tone is at −27 dBFS RMS. This value is 3 dB less than the working level.
You cannot change the level in the configuration. If you change the working
level, change `TONE_LEVEL_DB` in `levels.py` also.

To change the frequency of the tone, use the `--freq` option of `podio bleep`.
The default is 1000 Hz.

## 8. Correct a problem in the sound

Make these changes in `audio.toml`, not in the rig. Do the command again after
each change. A change takes seconds.

| Problem                                        | Change                                                                                      |
| ---------------------------------------------- | ------------------------------------------------------------------------------------------- |
| Constant hum, fan, air conditioner, or traffic | `[takes.X.afftdn] enabled = true`. If the noise stays, increase `reduction_db`.             |
| Room noise between the phrases                 | `[takes.X.gate] enabled = true`                                                             |
| The gate removes laughter or quiet words       | Decrease the offset: `threshold_db = "floor+8"`. Or increase `release_ms` to more than 250. |
| Noise that `afftdn` cannot remove              | `[takes.X.rnnoise] enabled = true`. Listen for damage to the laughter.                      |
| Too much low frequency                         | `[takes.X.highpass] f = 100`                                                                |
| The voice is dull                              | Use the `eq` stage. Refer to section 6.                                                     |
| Sharp "s" sounds                               | `[takes.X.deesser] intensity = 0.6`                                                         |
| The level goes from loud to quiet              | `[takes.X.compressor] ratio = 4`                                                            |

If a take is very different from usual, for example a different room or a
different microphone, change `audio.toml`. Do not change the rig.

### The message "gain clamped at the peak ceiling"

The peaks of the take do not permit sufficient gain. The take cannot get the
working level and stay below `peak_ceiling_db`. podio decreased the gain and
gave you this message. It did not clip the audio. The message gives the
difference in dB.

Do one of these two procedures:

- Decrease `working_level_db` until the message stops. Headroom has no cost in
  an intermediate file.
- Set `limiter = true` for that take. The limiter decreases the peaks, thus the
  take can get the working level.

A difference of some LU below the working level is not a problem. A difference
between the takes is a problem. This occurs when one take is clamped and the
other take is not clamped.

## 9. Audition one part of a take

An audition renders a short part only. Use it to examine one moment.

```sh
podio clean --range 21:30+45
```

This command renders 45 seconds from 21 minutes 30 seconds. podio writes
`NAME_audition.wav`, thus the audition does not replace a full render.

An audition does not censor the audio, because the times of a part are not the
times of the take.

## 10. Prepare the video files

`podio finish` does the full pass and then puts the audio on the related video:

```sh
podio finish        # makes ian_muxed.mov and josh_muxed.mov
podio finish ian    # one take only
```

Each video must have the name of its take, for example `ian.mp4`. All the
videos must be in the directory before podio starts. If a video is not there,
podio gives an error message and stops.

`podio finish` puts the intermediate files in `podio_artifacts/`. The MOV files
stay with the raw files. If a take has no censoring, podio uses its prepped
audio.

To put an audio file on a video without the pass, use `podio mux`:

```sh
podio mux episode.mp4 alex_censored.wav --out episode_censored.mov
```

podio does not encode the picture again. A `.mov` file and a `.mkv` file keep
the audio as 24-bit PCM. An `.mp4` file and an `.m4a` file cannot do this, thus
podio encodes the audio to AAC.

## 11. Master the mixdown

After the video editor exports the mixed episode, `podio master` sets the
delivery loudness: -16 LUFS integrated, with peaks below -1 dBTP.

```sh
podio master ep16.mp4                 # makes ep16_mastered.mp4 and ep16_mastered.mp3
podio master ep16.mp4 --out final/16  # makes final/16.mp4 and final/16.mp3
```

The mp4 file keeps the picture as exported, with the audio as 192 kbps AAC. The
mp3 file is the feed file, at 128 kbps and 44.1 kHz. podio makes the two files
from the same master, in four steps:

1. Measure the mixdown.
2. Apply one constant gain to get -16 LUFS.
3. Decrease the peaks above the ceiling with a true-peak limiter (alimiter,
   4x oversampling, ceiling -1.5 dB).
4. The limiter decreases the loudness. Thus podio adds the difference to the
   gain and does steps 2 and 3 again, until the result is within 0.2 LU.

podio measures the two files again and shows the results:

```
mixdown  I  -36.8 LUFS  TP -14.4 dB  gain +23.5 dB
mp4      I  -16.1 LUFS  TP  -1.4 dB
mp3      I  -16.5 LUFS  TP  -1.9 dB
```

A `WARN` line shows that a file is more than 1 LU from -16 LUFS, or has a peak
above -1 dBTP. This step does not change the takes. They stay at the working
level. This is the only step that sets the loudness of the mix — refer to
[ADR 0003](adr/0003-podio-masters-the-nle-mixdown.md).

## 12. Record a bumper

```sh
podio devices                        # shows the microphones
podio bumper                         # writes bumper.wav
podio bumper outro.wav --device 2    # uses a number from podio devices
```

Push `q` to stop the recording.

podio records one channel at 48 kHz and writes 24-bit audio. This is the same
form as a prepped take. The chain does not operate on a bumper.

The numbers of `podio devices` are positions in that list. The numbers change
when you connect a device. A name is more stable:

```sh
podio bumper --device "RØDE PodMic USB"
```

`podio bumper` is the only command that does not write over its output file. To
record over a file, use the `--force` option.

## 13. Command reference

| Command           | Function                                               |
| ----------------- | ------------------------------------------------------ |
| `podio run`       | Cleans and censors each take of the episode.           |
| `podio finish`    | Does `run`, then puts the audio on the related videos. |
| `podio clean`     | Cleans the takes only. It transcribes nothing.         |
| `podio detect`    | Makes a manifest and a transcript from one file.       |
| `podio bleep`     | Makes censored audio from one file and one manifest.   |
| `podio mux`       | Puts an audio file on a video file.                    |
| `podio master`    | Sets the delivery loudness of the mixdown.             |
| `podio devices`   | Shows the microphones of this machine.                 |
| `podio bumper`    | Records a bumper.                                      |
| `podio normalize` | Decodes a file to 16 kHz, one channel.                 |

### Options of run, finish, and clean

| Option           | Default           | Function                                                     |
| ---------------- | ----------------- | ------------------------------------------------------------ |
| `TAKES`          | all the takes     | The names of the takes to process.                           |
| `-c`, `--config` | `audio.toml`      | The episode file.                                            |
| `--rigs`         | the included rigs | The directory of the rig files.                              |
| `--models`       | `$RNNOISE_MODELS` | The directory of the `.rnnn` files.                          |
| `--range`        | none              | Render one part: `START+SECONDS`. Not in `finish`.           |
| `--dry-run`      | off               | Measure and show the chain. Render nothing. Not in `finish`. |
| `--review`       | off               | Stop after the manifests. `run` only.                        |
| `--redetect`     | off               | Detect again over a changed manifest. Not in `clean`.        |
| `--artifacts`    | `podio_artifacts` | The directory for intermediate files. `finish` only.         |

### Options for the detection

These options are available in `run`, `finish`, and `detect`.

| Option             | Default           | Function                                                    |
| ------------------ | ----------------- | ----------------------------------------------------------- |
| `--wordlist`       | the included list | A different word list.                                      |
| `--inset`          | `0.03`            | Decrease each span by this quantity of seconds at each end. |
| `--min-confidence` | `0.0`             | Remove the detections below this value.                     |
| `--model`          | `base.en`         | The WhisperX model. `large-v3` is more accurate but slower. |
| `--asr-device`     | `cpu`             | The processor for WhisperX: `cpu` or `cuda`.                |
| `--language`       | `en`              | The language of the speech.                                 |

The `--inset` option keeps the first sound and the last sound of the word
audible. A span that becomes empty is removed. Two spans that touch become one
span.

### Other options

| Command     | Option      | Default               | Function                                               |
| ----------- | ----------- | --------------------- | ------------------------------------------------------ |
| `detect`    | `--out`     | `manifest.json`       | The manifest file. The transcript gets a related name. |
| `bleep`     | `--out`     | `censored.wav`        | The output file.                                       |
| `bleep`     | `--freq`    | `1000`                | The frequency of the tone in Hz.                       |
| `mux`       | `--out`     | `SOURCE_muxed.mov`    | The output file.                                       |
| `master`    | `--out`     | `VIDEO_mastered`      | The output path, without the extension.                |
| `bumper`    | `--device`  | the system microphone | A number or a name.                                    |
| `bumper`    | `--force`   | off                   | Record over an existing file.                          |
| `normalize` | `--out`     | `normalized.wav`      | The output file.                                       |
| all         | `--version` | —                     | Show the version and stop.                             |
