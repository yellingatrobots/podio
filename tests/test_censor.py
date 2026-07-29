import os

from podio.censor import (
    censored_path,
    is_hand_edited,
    manifest_path,
    transcript_path,
)


def test_artifacts_are_named_after_the_take(tmp_path):
    assert manifest_path(tmp_path, "ian") == tmp_path / "ian.manifest.json"
    assert transcript_path(tmp_path, "ian") == tmp_path / "ian.transcript.json"
    assert censored_path(tmp_path, "ian") == tmp_path / "ian_censored.wav"


def write_pair(tmp_path, manifest_mtime: float, transcript_mtime: float):
    manifest = manifest_path(tmp_path, "ian")
    transcript = transcript_path(tmp_path, "ian")
    manifest.write_text("{}")
    transcript.write_text("{}")
    os.utime(manifest, (manifest_mtime, manifest_mtime))
    os.utime(transcript, (transcript_mtime, transcript_mtime))
    return manifest, transcript


def test_a_manifest_newer_than_its_transcript_was_edited_by_hand(tmp_path):
    """Detection writes both together; only a human touches one afterwards."""
    manifest, transcript = write_pair(tmp_path, 2000, 1000)

    assert is_hand_edited(manifest, transcript) is True


def test_a_manifest_written_by_detection_is_not_hand_edited(tmp_path):
    manifest, transcript = write_pair(tmp_path, 1000, 1000)

    assert is_hand_edited(manifest, transcript) is False


def test_a_manifest_older_than_its_transcript_is_not_hand_edited(tmp_path):
    manifest, transcript = write_pair(tmp_path, 1000, 2000)

    assert is_hand_edited(manifest, transcript) is False


def test_nothing_is_hand_edited_when_there_is_no_manifest_yet(tmp_path):
    manifest = manifest_path(tmp_path, "ian")
    transcript = transcript_path(tmp_path, "ian")

    assert is_hand_edited(manifest, transcript) is False


def test_a_manifest_with_no_transcript_beside_it_counts_as_hand_edited(tmp_path):
    """No transcript means nothing proves detection wrote it; assume a human did."""
    manifest = manifest_path(tmp_path, "ian")
    manifest.write_text("{}")

    assert is_hand_edited(manifest, transcript_path(tmp_path, "ian")) is True
