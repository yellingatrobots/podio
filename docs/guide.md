# podio user guide

This guide gives the steps to make the recordings of one podcast episode ready
for production. For the design of the tool and for the development steps, read
the [README](../README.md).

## 1. Words in this guide

| Word              | Meaning                                                               |
| ----------------- | --------------------------------------------------------------------- |
| take              | One recording. It has one speaker and one episode.                    |
| prep              | The full procedure on one take. The command is `podio prep`.          |
| prepped take      | The output of prep. It is ready for production.                       |
| rig               | A file with the stable setup of one speaker. It lists all the stages. |
| stage             | One step in the chain. The gate is an example.                        |
| chain             | The sequence of stages. podio applies the chain to each take.         |
| delivery loudness | −16 LUFS integrated, with peaks below −1 dBTP.                        |
| noise floor       | The level of the quiet parts of a take.                               |
| span              | A start time and an end time. podio puts a tone on this part.         |
| manifest          | A JSON file with all the spans of one take.                           |
| transcript        | A JSON file with each word of a take and its times.                   |
| bumper            | A recorded introduction, transition, or end message.                  |

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

Without nix, use uv in the directory of the source:

```sh
uv tool install .
```

This installation does not include ffmpeg. Install ffmpeg with the OpenAL
capture device, or set `PODIO_FFMPEG` to the path of an ffmpeg.

podio needs the model data of WhisperX. The first detection downloads
approximately 141 MB. Subsequent detections do not use the network.

To show the version, enter this command:

```sh
podio --version
```

## 3. Prepare an episode

Do these steps in the directory of the episode.

1. Put one file in the directory for each speaker. Use the name of the speaker,
   for example `ian.mp4` and `josh.mp4`. A file can be a video or a `.wav`.
2. Enter this command:

   ```sh
   podio prep ian.mp4 josh.mp4
   ```

podio does these steps on each file:

1. It applies the chain of the rig to the audio, at 48 kHz.
2. It sets the audio to the delivery loudness: −16 LUFS, peaks below −1 dBTP.
3. It transcribes the audio and finds the words of the word list.
4. It puts a tone on each word that it found.
5. It writes the audio back into a file of the same type. In a video, it moves
   the audio by the `audio_delay_frames` of the rig.

podio writes one file for each input:

| Input      | Output             | Contents                                         |
| ---------- | ------------------ | ------------------------------------------------ |
| `NAME.mp4` | `NAME_prepped.mp4` | The same picture, and the audio as 192 kbps AAC. |
| `NAME.wav` | `NAME_prepped.wav` | The audio, 24-bit, 48 kHz.                       |

Import the prepped files into the video editor. Do not change their loudness.

If a `NAME.wav` is in the same directory as `NAME.mp4`, podio uses the audio of
the `.wav` file and the picture of the `.mp4` file. podio does not synchronize
them. The two files must start at the same time.

podio examines all the files before it starts. If a file is missing, or if
podio cannot find the rig of a file, podio stops and writes nothing. Then podio
does the files at the same time. If one file fails, podio completes the other
files, and then it gives an error message.

| Option            | Function                                                   |
| ----------------- | ---------------------------------------------------------- |
| `--no-bleep`      | Do not transcribe and do not put tones on the audio.       |
| `-j N`            | Do N files at the same time. The default is all the files. |
| `--keep-temp DIR` | Keep the intermediate files of each take in `DIR/NAME`.    |

The intermediate files are in a temporary directory. podio deletes them when it
completes. To examine them, use `--keep-temp`.

## 4. The episode file

podio finds the rig with the name of the file: `ian.mp4` uses the rig `ian`.
If this is correct, you do not need an episode file.

Put an `audio.toml` file in the directory of the files to change the settings
for one recording. This is an example:

```toml
[censor]
wordlist = "words.toml"        # for all the takes

[takes.ian]
rig = "ian_dji"                # a different rig for ian.mp4

[takes.ian.afftdn]             # a fan was in operation in this episode
enabled = true

[takes.ian.censor]
wordlist = "ian_words.toml"    # for ian.mp4 only
```

| Key                             | Default              | Function                                 |
| ------------------------------- | -------------------- | ---------------------------------------- |
| `censor.wordlist`               | the included list    | A different word list.                   |
| `takes.NAME.rig`                | the name of the file | The rig file to use.                     |
| `takes.NAME.audio_delay_frames` | the rig              | A different audio delay for one take.    |
| `takes.NAME.censor.wordlist`    | the episode value    | A different word list for one take.      |
| `takes.NAME.STAGE`              | the rig              | A change to one stage for one take.      |

`NAME` is the name of the file without the extension. Only the stages in the
rig are available. podio gives an error message for an unknown stage or an
unknown key.

## 5. Make a rig for your voice

A rig holds the stable setup of one speaker: the microphone, the room, and the
usual tone. The tool includes the rigs `ian` and `josh`.

1. Make a directory for your rigs.
2. Copy an included rig into it. Use the name of the speaker, for example
   `alex.toml`. The included rigs are in `src/podio/data/rigs/` in the source.
3. Change the values. Refer to section 6 for each stage.
4. Give the directory to podio with the `--rigs` option:

   ```sh
   podio prep alex.mp4 --rigs ./my_rigs
   ```

The directory must have one file for each take, or for each rig that
`audio.toml` names.

A rig can also set `audio_delay_frames` before its stages. Use it when the
audio and the picture of the camera are not synchronized:

```toml
audio_delay_frames = 4   # the audio is 4 frames before the picture
```

A positive value moves the audio later. A negative value moves the audio
earlier. podio gets the frame rate from the video. podio does not move the
audio of a `.wav` output, because it has no picture. The rigs `josh` and
`josh_dji` set 4. If you use a different camera for one episode, set
`[takes.josh] audio_delay_frames = 0` in `audio.toml`.

A rig lists all the stages, and it sets `enabled = false` for the stages that
are not usually necessary. Keep this rule: a rig holds what does not change,
and `audio.toml` holds what changes with one recording.

## 6. The stages

The chain is always in this sequence:

```
highpass → afftdn → rnnoise → gate → eq → compressor → deesser
```

After the chain, podio sets the take to -16 LUFS integrated with one constant
gain, and a true-peak limiter keeps the peaks below -1 dBTP. The limiter
decreases the loudness a little, thus podio adds the difference to the gain
and does the two steps again, until the result is within 0.2 LU.

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
with the `--rnnoise-models` option. If podio cannot find the file, it gives an error
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

`podio prep` censors each take after it sets the loudness. To prepare a take
without censoring, use `--no-bleep`.

### The manifest

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

To correct a manifest, do these steps:

1. Prepare the take with `--keep-temp`:

   ```sh
   podio prep ian.wav --keep-temp kept
   ```

2. Change the times, or remove a span, in `kept/ian/ian_manifest.json`.
3. Put the tones on the cleaned take again:

   ```sh
   podio debug bleep kept/ian/ian_cleaned.wav kept/ian/ian_manifest.json --out ian_prepped.wav
   ```

4. For a video, put the audio on the picture:

   ```sh
   podio debug mux ian.mp4 ian_prepped.wav --out ian_prepped.mov
   ```

### The word list

The included word list is `src/podio/data/wordlist.toml`. It has the terms and
an `allowlist` of words that podio must not censor.

podio finds a full word or a full phrase. It ignores the case and the
punctuation. It does not find a part of a word, thus the words "class",
"assassin", and "cockpit" are safe.

To use a different list, give the file in `audio.toml`, or use the `--wordlist`
option.

### The tone

The tone is at −19 dBFS RMS. This value is 3 dB less than the delivery
loudness, thus the peaks of the tone are at −16 dBFS. You cannot change the
level in the configuration.

To change the frequency of the tone, use the `--freq` option of
`podio debug bleep`. The default is 1000 Hz.

## 8. Correct a problem in the sound

First, examine the noise floor of each take. This command measures the takes
and shows the chain. It writes nothing:

```sh
podio debug clean ian.mp4 josh.mp4 --dry-run
```

A value of −75 dB or lower is a quiet room. A higher value shows that a machine
was in operation.

Make these changes in `audio.toml`, not in the rig. To hear the result without
the transcription, enter `podio debug clean ian.mp4`. It writes
`ian_cleaned.wav`.

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
| You hear the clap before the clapper closes    | `[takes.X] audio_delay_frames = N`, where N is the number of frames between them.           |
| You hear the clap after the clapper closes     | `[takes.X] audio_delay_frames = -N`                                                         |

If a take is very different from usual, for example a different room or a
different microphone, change `audio.toml`. Do not change the rig.

## 9. Record a bumper

```sh
podio devices                        # shows the microphones
podio bumper                         # writes bumper.wav
podio bumper outro.wav --device 2    # uses a number from podio devices
```

Push `q` to stop the recording.

podio records one channel at 48 kHz and writes 24-bit audio. The chain does
not operate on a bumper, and its loudness is as recorded. To set it to the
loudness of the takes, enter this command:

```sh
podio prep intro.wav --no-bleep      # writes intro_prepped.wav
```

This needs a rig with the name of the file, or an `audio.toml` that gives one.

The numbers of `podio devices` are positions in that list. The numbers change
when you connect a device. A name is more stable:

```sh
podio bumper --device "RØDE PodMic USB"
```

`podio bumper` is the only command that does not write over its output file. To
record over a file, use the `--force` option.

## 10. Command reference

| Command                 | Function                                                            |
| ----------------------- | ------------------------------------------------------------------- |
| `podio prep FILE...`    | Makes each file ready for production.                               |
| `podio devices`         | Shows the microphones of this machine.                              |
| `podio bumper [OUT]`    | Records a bumper.                                                   |
| `podio debug clean`     | Applies the chain and the loudness only. Writes `NAME_cleaned.wav`. |
| `podio debug detect`    | Makes a manifest and a transcript from one file.                    |
| `podio debug bleep`     | Puts the tones on one file from one manifest.                       |
| `podio debug mux`       | Puts an audio file on a video file.                                 |
| `podio debug normalize` | Decodes a file to 16 kHz, one channel.                              |

### Options of prep

| Option             | Default           | Function                                                    |
| ------------------ | ----------------- | ----------------------------------------------------------- |
| `--no-bleep`       | off               | Do not transcribe and do not put tones on the audio.        |
| `-j`, `--jobs`     | all the files     | The number of files at the same time.                       |
| `--keep-temp`      | none              | Keep the intermediate files in this directory.              |
| `--model`          | `base.en`         | The WhisperX model. `large-v3` is more accurate but slower. |
| `--wordlist`       | the included list | A different word list for all the files.                    |
| `--rigs`           | the included rigs | The directory of the rig files. Also in `debug clean`.      |
| `--rnnoise-models` | `$RNNOISE_MODELS` | The directory of the `.rnnn` files. Also in `debug clean`.  |

### Options of debug detect

| Option             | Default           | Function                                                    |
| ------------------ | ----------------- | ----------------------------------------------------------- |
| `--out`            | `manifest.json`   | The manifest file. The transcript gets a related name.      |
| `--wordlist`       | the included list | A different word list.                                      |
| `--inset`          | `0.03`            | Decrease each span by this quantity of seconds at each end. |
| `--min-confidence` | `0.0`             | Remove the detections below this value.                     |
| `--model`          | `base.en`         | The WhisperX model.                                         |
| `--asr-device`     | `cpu`             | The processor for WhisperX: `cpu` or `cuda`.                |
| `--language`       | `en`              | The language of the speech.                                 |

The `--inset` option keeps the first sound and the last sound of the word
audible. A span that becomes empty is removed. Two spans that touch become one
span. `podio prep` uses the defaults.

### Other options

| Command           | Option      | Default               | Function                                   |
| ----------------- | ----------- | --------------------- | ------------------------------------------ |
| `debug clean`     | `--dry-run` | off                   | Measure and show the chain. Write nothing. |
| `debug bleep`     | `--out`     | `censored.wav`        | The output file.                           |
| `debug bleep`     | `--freq`    | `1000`                | The frequency of the tone in Hz.           |
| `debug mux`       | `--out`     | `VIDEO_muxed.mov`     | The output file.                           |
| `debug normalize` | `--out`     | `normalized.wav`      | The output file.                           |
| `bumper`          | `--device`  | the system microphone | A number or a name.                        |
| `bumper`          | `--force`   | off                   | Record over an existing file.              |
| all               | `--version` | —                     | Show the version and stop.                 |
