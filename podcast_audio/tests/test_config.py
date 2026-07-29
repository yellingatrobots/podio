import pytest

from config import load_episode, merge_chain

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
