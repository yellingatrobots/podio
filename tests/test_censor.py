import json
import os

from podio.censor import (
    censored_path,
    detect_into,
    is_hand_edited,
    manifest_path,
    transcript_path,
)
from podio.cli import main
from podio.manifest import Word
from podio.wordlist import WordList

WORDLIST = WordList.from_dict({"terms": ["damn"]})


def test_artifacts_are_named_after_the_take(tmp_path):
    assert manifest_path(tmp_path, "ian") == tmp_path / "ian_manifest.json"
    assert transcript_path(tmp_path, "ian") == tmp_path / "ian_transcript.json"
    assert censored_path(tmp_path, "ian") == tmp_path / "ian_censored.wav"


class RecordingTranscriber:
    """Records the path it was asked to read, and reports one word."""

    def __init__(self):
        self.read = None

    def transcribe(self, audio_path: str):
        self.read = audio_path
        return [Word(text="damn", start=1.0, end=1.4, confidence=0.9)]


def test_detection_hands_the_transcriber_the_take_itself(tmp_path):
    """WhisperX decodes to mono 16 kHz on its own; converting first did it twice."""
    prepped = tmp_path / "ian_prepped.wav"
    prepped.write_bytes(b"")
    transcriber = RecordingTranscriber()

    detect_into(
        prepped, tmp_path, "ian", WORDLIST, transcriber,
        inset=0.03, min_confidence=0.0,
    )

    assert transcriber.read == str(prepped)


def test_detect_uses_matching_underscore_names(tmp_path, monkeypatch):
    audio = tmp_path / "ian.wav"
    audio.write_bytes(b"")
    manifest = tmp_path / "ian_manifest.json"
    monkeypatch.setattr(
        "podio.cli.WhisperXTranscriber", lambda **_kwargs: RecordingTranscriber()
    )

    assert main(["detect", str(audio), "--out", str(manifest)]) == 0
    assert manifest.exists()
    assert (tmp_path / "ian_transcript.json").exists()


def test_the_manifest_points_at_the_take_that_was_read(tmp_path):
    prepped = tmp_path / "ian_prepped.wav"
    prepped.write_bytes(b"")

    written, spans = detect_into(
        prepped, tmp_path, "ian", WORDLIST, RecordingTranscriber(),
        inset=0.03, min_confidence=0.0,
    )

    assert spans == 1
    assert json.loads(written.read_text())["audio_path"] == str(prepped)


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
