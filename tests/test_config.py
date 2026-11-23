import pytest

from podio.config import load_take, merge_chain

RIG_CHAIN = [
    {"name": "highpass", "f": 80},
    {"name": "afftdn", "enabled": False},
    {"name": "rnnoise", "enabled": False, "model": "lq"},
    {"name": "gate", "enabled": False, "threshold_db": "floor+12"},
    {"name": "compressor", "threshold_db": -18},
]


def test_a_take_with_no_overrides_uses_the_rig_chain_unchanged():
    assert merge_chain(RIG_CHAIN, {}) == RIG_CHAIN


def test_an_override_patches_one_parameter_and_leaves_the_rest():
    merged = merge_chain(RIG_CHAIN, {"compressor": {"ratio": 4}})
    compressor = merged[-1]
    assert compressor == {"name": "compressor", "threshold_db": -18, "ratio": 4}


def test_an_override_can_switch_on_a_stage_the_rig_leaves_off():
    merged = merge_chain(RIG_CHAIN, {"afftdn": {"enabled": True, "reduction_db": 14}})
    assert merged[1] == {"name": "afftdn", "enabled": True, "reduction_db": 14}


def test_overriding_preserves_the_rig_chain_order():
    merged = merge_chain(RIG_CHAIN, {"gate": {"enabled": True}})
    assert [s["name"] for s in merged] == [s["name"] for s in RIG_CHAIN]


def test_the_rig_chain_is_not_mutated_by_merging():
    merge_chain(RIG_CHAIN, {"compressor": {"ratio": 4}})
    assert RIG_CHAIN[-1] == {"name": "compressor", "threshold_db": -18}


def test_overriding_a_stage_the_rig_does_not_have_is_an_error():
    with pytest.raises(ValueError, match="deesser"):
        merge_chain(RIG_CHAIN, {"deesser": {"intensity": 0.6}})


IAN_RIG = """
[[stage]]
name = "highpass"
f = 80

[[stage]]
name = "afftdn"
enabled = false
"""


# One file at a time: the take is named after the file, and audio.toml beside
# it is optional.


def rigs_dir(tmp_path, **rigs):
    path = tmp_path / "rigs"
    path.mkdir()
    for name, body in rigs.items():
        (path / f"{name}.toml").write_text(body)
    return path


def test_a_file_named_after_a_rig_needs_no_audio_toml(tmp_path):
    rigs = rigs_dir(tmp_path, ian=IAN_RIG)
    take = load_take(tmp_path / "ian.mp4", rigs)

    assert take.name == "ian"
    assert take.source == tmp_path / "ian.mp4"
    assert [s["name"] for s in take.chain] == ["highpass", "afftdn"]
    assert take.censor.wordlist is None


def test_a_wav_beside_a_video_is_the_take_s_audio(tmp_path):
    rigs = rigs_dir(tmp_path, ian=IAN_RIG)
    (tmp_path / "ian.wav").write_bytes(b"")

    assert load_take(tmp_path / "ian.mp4", rigs).source == tmp_path / "ian.wav"


def test_a_file_with_no_rig_of_its_name_says_how_to_name_one(tmp_path):
    rigs = rigs_dir(tmp_path, ian=IAN_RIG)
    with pytest.raises(ValueError, match=r"DJI_0042.*ian.*audio\.toml"):
        load_take(tmp_path / "DJI_0042.mp4", rigs)


def test_audio_toml_beside_the_file_picks_the_rig_and_overrides(tmp_path):
    rigs = rigs_dir(tmp_path, ian_dji=IAN_RIG)
    (tmp_path / "audio.toml").write_text(
        """
        [takes.ian]
        rig = "ian_dji"

        [takes.ian.afftdn]
        enabled = true
        """
    )
    take = load_take(tmp_path / "ian.mp4", rigs)
    assert take.chain[1] == {"name": "afftdn", "enabled": True}


def test_wordlists_resolve_against_the_file_s_directory_take_over_episode(tmp_path):
    rigs = rigs_dir(tmp_path, ian=IAN_RIG, josh=IAN_RIG)
    (tmp_path / "audio.toml").write_text(
        """
        [censor]
        wordlist = "words.toml"

        [takes.ian.censor]
        wordlist = "ian_words.toml"
        """
    )
    assert load_take(tmp_path / "ian.mp4", rigs).censor.wordlist == (
        tmp_path / "ian_words.toml"
    )
    assert load_take(tmp_path / "josh.mp4", rigs).censor.wordlist == (
        tmp_path / "words.toml"
    )


@pytest.mark.parametrize("toml, unknown", [
    ("working_level_db = -24.0", "working_level_db"),
    ("[censor]\nenabled = false", "enabled"),
    ('[takes.ian]\nfile = "ian.wav"', "file"),
    ("[takes.ian]\nlimiter = true", "limiter"),
    ("[takes.ian.censor]\nenabled = false", "enabled"),
])
def test_settings_podio_no_longer_reads_are_errors(tmp_path, toml, unknown):
    rigs = rigs_dir(tmp_path, ian=IAN_RIG)
    (tmp_path / "audio.toml").write_text(toml)
    with pytest.raises(ValueError, match=unknown):
        load_take(tmp_path / "ian.mp4", rigs)


# Audio that runs ahead of the picture is a property of the recording rig, so
# the rig sets the correction and an episode can change it for one take.


def test_a_take_has_no_audio_delay_unless_its_rig_sets_one(tmp_path):
    rigs = rigs_dir(tmp_path, ian=IAN_RIG)
    assert load_take(tmp_path / "ian.mp4", rigs).audio_delay_frames == 0


def test_a_rig_sets_the_audio_delay_in_frames(tmp_path):
    rigs = rigs_dir(tmp_path, josh="audio_delay_frames = 4\n" + IAN_RIG)
    take = load_take(tmp_path / "josh.mp4", rigs)
    assert take.audio_delay_frames == 4
    assert [s["name"] for s in take.chain] == ["highpass", "afftdn"]


def test_audio_toml_overrides_the_rig_s_audio_delay(tmp_path):
    rigs = rigs_dir(tmp_path, josh="audio_delay_frames = 4\n" + IAN_RIG)
    (tmp_path / "audio.toml").write_text("[takes.josh]\naudio_delay_frames = -2\n")
    assert load_take(tmp_path / "josh.mp4", rigs).audio_delay_frames == -2


@pytest.mark.parametrize("value", ["4.5", '"4"', "true"])
def test_an_audio_delay_that_is_not_whole_frames_is_an_error(tmp_path, value):
    rigs = rigs_dir(tmp_path, josh=f"audio_delay_frames = {value}\n" + IAN_RIG)
    with pytest.raises(ValueError, match="audio_delay_frames"):
        load_take(tmp_path / "josh.mp4", rigs)


def test_a_rig_given_by_name_configures_a_file_of_any_name(tmp_path):
    rigs = rigs_dir(tmp_path, josh=IAN_RIG)
    take = load_take(tmp_path / "intro.wav", rigs, rig="josh")

    assert take.name == "intro"
    assert [s["name"] for s in take.chain] == ["highpass", "afftdn"]


def test_a_rig_given_by_name_wins_over_audio_toml_and_keeps_its_overrides(tmp_path):
    rigs = rigs_dir(tmp_path, josh=IAN_RIG)
    (tmp_path / "audio.toml").write_text(
        """
        [takes.intro]
        rig = "missing"

        [takes.intro.afftdn]
        enabled = true
        """
    )
    take = load_take(tmp_path / "intro.wav", rigs, rig="josh")

    assert take.chain[1] == {"name": "afftdn", "enabled": True}


def test_a_rig_given_by_name_that_does_not_exist_is_an_error(tmp_path):
    rigs = rigs_dir(tmp_path, josh=IAN_RIG)
    with pytest.raises(ValueError, match=r"no rig 'jsoh' for intro\.wav.*josh"):
        load_take(tmp_path / "intro.wav", rigs, rig="jsoh")
