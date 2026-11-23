"""podio init: an audio.toml that lists every setting, each at its default."""

import re
import tomllib
from pathlib import Path

import pytest

from podio.cli import RIGS, main
from podio.config import EPISODE_CONFIG, episode_template, find_takes, load_take
from podio.stages import build_stage

SETTING = re.compile(r"^# (?=\[|[a-z_]+ = )")


def uncomment(template: str) -> str:
    """Every setting switched on, the prose left as comments."""
    return "\n".join(SETTING.sub("", line) for line in template.splitlines())


def built(take) -> list:
    return [build_stage(spec) for spec in take.chain]


def touch(directory: Path, *names: str) -> list[Path]:
    for name in names:
        (directory / name).write_bytes(b"")
    return [directory / name for name in names]


def test_as_written_the_template_changes_nothing(tmp_path):
    media = touch(tmp_path, "josh.mp4", "ian.wav")
    assert tomllib.loads(episode_template(media, RIGS)) == {}


@pytest.mark.parametrize("name", ["josh.mp4", "ian.wav"])
def test_every_setting_uncommented_is_what_the_take_already_gets(tmp_path, name):
    (media,) = touch(tmp_path, name)
    plain = load_take(media, RIGS)

    (tmp_path / EPISODE_CONFIG).write_text(uncomment(episode_template([media], RIGS)))
    spelled_out = load_take(media, RIGS)

    assert built(spelled_out) == built(plain)
    assert spelled_out.audio_delay_frames == plain.audio_delay_frames
    assert spelled_out.censor == plain.censor


def test_settings_the_rig_leaves_to_the_stage_are_listed_too(tmp_path):
    template = episode_template(touch(tmp_path, "josh.mp4"), RIGS)

    assert "# audio_delay_frames = 4" in template
    assert "# [takes.josh.afftdn]" in template
    assert "# track_noise = true" in template


def test_a_take_with_no_rig_of_its_name_lists_the_rigs_to_choose_from(tmp_path):
    template = episode_template(touch(tmp_path, "intro.wav"), RIGS)

    assert re.search(r'^# rig = "" .*ian, ian_dji, josh, josh_dji', template, re.M)
    assert "[takes.intro." not in template
    assert tomllib.loads(template) == {}


def test_the_takes_are_the_media_podio_did_not_write_one_per_name(tmp_path):
    touch(tmp_path, "josh.mp4", "josh.wav", "ian.mov", "ian_prepped.mov",
          "josh_cleaned.wav", "josh_muxed.mov", "notes.txt", EPISODE_CONFIG)

    assert [p.name for p in find_takes(tmp_path)] == ["ian.mov", "josh.mp4"]


def test_init_writes_audio_toml_beside_the_takes_and_keeps_an_existing_one(
    tmp_path, monkeypatch
):
    touch(tmp_path, "josh.mp4")
    monkeypatch.chdir(tmp_path)
    config = tmp_path / EPISODE_CONFIG

    assert main(["init"]) == 0
    assert "# [takes.josh]" in config.read_text()

    config.write_text("# mine\n")
    assert main(["init"]) == 1
    assert config.read_text() == "# mine\n"

    assert main(["init", "--force"]) == 0
    assert "# [takes.josh]" in config.read_text()


def test_init_names_takes_by_file_and_writes_beside_them(tmp_path):
    (bumper,) = touch(tmp_path, "intro.wav")
    assert main(["init", str(bumper)]) == 0
    assert "# [takes.intro]" in (tmp_path / EPISODE_CONFIG).read_text()


def test_init_with_nothing_to_configure_is_an_error(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert main(["init"]) == 1
    assert not (tmp_path / EPISODE_CONFIG).exists()
