import pytest

from podio.config import load_episode, scaffold, stub_toml


def make_takes(tmp_path, *names):
    for name in names:
        (tmp_path / name).write_bytes(b"")


def rigs_at(tmp_path, *names):
    rigs = tmp_path / "rigs"
    rigs.mkdir(exist_ok=True)
    for name in names:
        (rigs / f"{name}.toml").write_text("[[stage]]\nname = 'highpass'\nf = 80\n")
    return rigs


def test_a_stub_lists_every_take_it_found(tmp_path):
    make_takes(tmp_path, "ian.wav", "josh.wav")

    toml = stub_toml(tmp_path, rigs_at(tmp_path, "ian", "josh"))

    assert "[takes.ian]" in toml
    assert 'file = "ian.wav"' in toml
    assert "[takes.josh]" in toml


def test_a_take_with_a_matching_rig_is_pointed_at_it(tmp_path):
    make_takes(tmp_path, "ian.wav")

    toml = stub_toml(tmp_path, rigs_at(tmp_path, "ian"))

    assert 'rig  = "ian"' in toml


def test_a_take_with_no_matching_rig_is_flagged(tmp_path):
    make_takes(tmp_path, "stranger.wav")

    toml = stub_toml(tmp_path, rigs_at(tmp_path, "ian"))

    assert "stranger" in toml
    assert "no rig" in toml.lower()


def test_podio_s_own_outputs_are_never_read_back_as_takes(tmp_path):
    """A second run must not scaffold the first run's renders as new takes."""
    make_takes(
        tmp_path,
        "ian.wav",
        "ian_prepped.wav",
        "ian_censored.wav",
        "ian_audition.wav",
    )

    toml = stub_toml(tmp_path, rigs_at(tmp_path, "ian"))

    assert "[takes.ian]" in toml
    assert "prepped" not in toml
    assert "censored" not in toml
    assert "audition" not in toml


def test_a_directory_with_no_takes_says_so(tmp_path):
    with pytest.raises(ValueError, match="no .wav"):
        stub_toml(tmp_path, rigs_at(tmp_path, "ian"))


def test_the_stub_it_writes_is_loadable(tmp_path):
    """Whatever is scaffolded has to survive being read straight back."""
    make_takes(tmp_path, "ian.wav")
    rigs = rigs_at(tmp_path, "ian")
    config = tmp_path / "audio.toml"

    assert scaffold(config, rigs, ask=lambda _: True) is True

    episode = load_episode(config, rigs)
    assert [t.name for t in episode.takes] == ["ian"]
    assert episode.working_level_db == -24.0


def test_declining_the_prompt_writes_nothing(tmp_path):
    make_takes(tmp_path, "ian.wav")
    config = tmp_path / "audio.toml"

    assert scaffold(config, rigs_at(tmp_path, "ian"), ask=lambda _: False) is False
    assert not config.exists()


def test_an_existing_config_is_never_overwritten(tmp_path):
    make_takes(tmp_path, "ian.wav")
    config = tmp_path / "audio.toml"
    config.write_text("# mine\n")

    assert scaffold(config, rigs_at(tmp_path, "ian"), ask=lambda _: True) is False
    assert config.read_text() == "# mine\n"
