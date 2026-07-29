import pytest

from podio.config import load_episode, merge_chain

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


def write_episode(tmp_path, episode_toml, rigs):
    (tmp_path / "rigs").mkdir()
    for name, body in rigs.items():
        (tmp_path / "rigs" / f"{name}.toml").write_text(body)
    config = tmp_path / "audio.toml"
    config.write_text(episode_toml)
    return config, tmp_path / "rigs"


IAN_RIG = """
[[stage]]
name = "highpass"
f = 80

[[stage]]
name = "afftdn"
enabled = false
"""


def test_load_episode_resolves_takes_against_their_rigs(tmp_path):
    config, rigs = write_episode(
        tmp_path,
        """
        working_level_db = -20.0
        peak_ceiling_db = -3.0

        [takes.ian]
        file = "ian.wav"
        rig = "ian"

        [takes.ian.afftdn]
        enabled = true
        """,
        {"ian": IAN_RIG},
    )
    episode = load_episode(config, rigs)

    assert episode.working_level_db == -20.0
    assert episode.peak_ceiling_db == -3.0
    assert len(episode.takes) == 1

    take = episode.takes[0]
    assert take.name == "ian"
    assert take.source == tmp_path / "ian.wav"
    assert take.limiter is False
    assert take.chain[1] == {"name": "afftdn", "enabled": True}


def test_a_take_can_ask_for_the_limiter(tmp_path):
    config, rigs = write_episode(
        tmp_path,
        """
        [takes.josh]
        file = "josh.wav"
        rig = "ian"
        limiter = true
        """,
        {"ian": IAN_RIG},
    )
    assert load_episode(config, rigs).takes[0].limiter is True


def test_a_missing_rig_names_the_file_it_looked_for(tmp_path):
    config, rigs = write_episode(
        tmp_path,
        """
        [takes.ian]
        file = "ian.wav"
        rig = "nobody"
        """,
        {"ian": IAN_RIG},
    )
    with pytest.raises(ValueError, match="nobody.toml"):
        load_episode(config, rigs)


def test_an_episode_with_no_takes_is_an_error(tmp_path):
    config, rigs = write_episode(tmp_path, "working_level_db = -20.0", {"ian": IAN_RIG})
    with pytest.raises(ValueError, match="no takes"):
        load_episode(config, rigs)


def test_a_take_is_censored_by_default(tmp_path):
    config, rigs = write_episode(
        tmp_path,
        """
        [takes.ian]
        file = "ian.wav"
        rig = "ian"
        """,
        {"ian": IAN_RIG},
    )
    censor = load_episode(config, rigs).takes[0].censor

    assert censor.enabled is True
    assert censor.wordlist is None


def test_an_episode_can_switch_censoring_off_for_every_take(tmp_path):
    config, rigs = write_episode(
        tmp_path,
        """
        [censor]
        enabled = false

        [takes.ian]
        file = "ian.wav"
        rig = "ian"
        """,
        {"ian": IAN_RIG},
    )
    assert load_episode(config, rigs).takes[0].censor.enabled is False


def test_a_take_can_switch_censoring_off_on_its_own(tmp_path):
    config, rigs = write_episode(
        tmp_path,
        """
        [takes.ian]
        file = "ian.wav"
        rig = "ian"

        [takes.ian.censor]
        enabled = false

        [takes.josh]
        file = "josh.wav"
        rig = "ian"
        """,
        {"ian": IAN_RIG},
    )
    ian, josh = load_episode(config, rigs).takes

    assert ian.censor.enabled is False
    assert josh.censor.enabled is True


def test_a_take_censor_block_is_not_read_as_a_stage_override(tmp_path):
    """`censor` is not a stage, so it must not be matched against the rig chain."""
    config, rigs = write_episode(
        tmp_path,
        """
        [takes.ian]
        file = "ian.wav"
        rig = "ian"

        [takes.ian.censor]
        enabled = false
        """,
        {"ian": IAN_RIG},
    )
    take = load_episode(config, rigs).takes[0]

    assert [s["name"] for s in take.chain] == ["highpass", "afftdn"]


def test_a_wordlist_override_resolves_against_the_episode_directory(tmp_path):
    config, rigs = write_episode(
        tmp_path,
        """
        [censor]
        wordlist = "extra_words.toml"

        [takes.ian]
        file = "ian.wav"
        rig = "ian"
        """,
        {"ian": IAN_RIG},
    )
    assert load_episode(config, rigs).takes[0].censor.wordlist == (
        tmp_path / "extra_words.toml"
    )
