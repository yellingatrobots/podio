from pathlib import Path

import pytest

from podio.levels import Measured
from podio.stages import build_chain, build_stage

MODELS = Path("/models")
IAN = Measured(floor_db=-51.5)
JOSH = Measured(floor_db=-77.7)


def filter_for(spec, measured=IAN):
    return build_stage(spec).filter(measured, MODELS)


def test_highpass():
    assert filter_for({"name": "highpass", "f": 80}) == "highpass=f=80"


def test_gate_converts_a_resolved_db_threshold_to_linear():
    got = filter_for({"name": "gate", "threshold_db": "floor+12"})
    assert got.startswith("agate=threshold=0.01059:")


def test_gate_threshold_tracks_the_take_it_is_measuring():
    quiet = filter_for({"name": "gate", "threshold_db": "floor+12"}, JOSH)
    assert quiet.startswith("agate=threshold=0.00052:")


def test_afftdn_defaults_its_noise_floor_to_the_measurement():
    assert filter_for({"name": "afftdn"}) == "afftdn=nf=-51.5:nr=12:tn=1"


def test_afftdn_clamps_to_the_range_ffmpeg_accepts():
    silent_booth = Measured(floor_db=-85.0)
    assert filter_for({"name": "afftdn"}, silent_booth) == "afftdn=nf=-80:nr=12:tn=1"


def test_rnnoise_resolves_the_model_against_the_models_directory(tmp_path):
    (tmp_path / "lq.rnnn").write_bytes(b"")
    got = build_stage({"name": "rnnoise", "model": "lq"}).filter(IAN, tmp_path)
    assert got == f"arnndn=m={tmp_path / 'lq.rnnn'}"


def test_rnnoise_says_which_model_file_is_missing(tmp_path):
    stage = build_stage({"name": "rnnoise", "model": "lq"})
    with pytest.raises(ValueError, match="RNNOISE_MODELS"):
        stage.filter(IAN, tmp_path)


def test_eq_emits_one_equalizer_per_band():
    got = filter_for(
        {"name": "eq", "bands": [{"f": 250, "width": 1.0, "gain_db": -2.5}]}
    )
    assert got == "equalizer=f=250:t=q:w=1:g=-2.5"


def test_compressor():
    got = filter_for({"name": "compressor", "threshold_db": -18, "ratio": 3})
    assert got == "acompressor=threshold=-18dB:ratio=3:attack=5:release=60"


def test_deesser():
    assert filter_for({"name": "deesser"}) == "deesser=i=0.4:f=0.5:m=0.5"


def test_unknown_stage_is_rejected_by_name():
    with pytest.raises(ValueError, match="denoiser"):
        build_stage({"name": "denoiser"})


def test_unknown_parameter_is_rejected():
    with pytest.raises(ValueError, match="thresold"):
        build_stage({"name": "gate", "thresold_db": -40})


def chain_of(specs, *, source_rate=48000, target_rate=48000):
    return build_chain(
        specs, IAN, MODELS, source_rate=source_rate, target_rate=target_rate
    )


def test_a_take_already_at_the_working_rate_is_not_resampled():
    assert chain_of([{"name": "highpass", "f": 80}]) == "highpass=f=80"


def test_a_take_at_another_rate_is_brought_to_the_working_rate_first():
    chain = chain_of([{"name": "highpass", "f": 80}], source_rate=44100)
    assert chain == "aresample=48000,highpass=f=80"


def test_disabled_stages_are_absent_from_the_chain():
    chain = chain_of(
        [
            {"name": "highpass", "f": 90},
            {"name": "rnnoise", "enabled": False},
            {"name": "deesser"},
        ]
    )
    assert chain == "highpass=f=90,deesser=i=0.4:f=0.5:m=0.5"


def test_rnnoise_refuses_a_working_rate_it_cannot_run_at():
    with pytest.raises(ValueError, match="rnnoise"):
        chain_of(
            [{"name": "rnnoise", "enabled": True}],
            source_rate=44100,
            target_rate=44100,
        )


def test_a_disabled_rnnoise_does_not_constrain_the_working_rate():
    chain = chain_of(
        [{"name": "rnnoise", "enabled": False}, {"name": "highpass", "f": 80}],
        source_rate=44100,
        target_rate=44100,
    )
    assert chain == "highpass=f=80"
