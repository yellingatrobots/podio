"""One class per stage.

Each stage declares its parameters in dB or plain units and emits the ffmpeg
filter fragment for them. ffmpeg's own units — agate's linear thresholds,
afftdn's clamped noise floor — are converted here so config never has to know
about them.
"""

from pathlib import Path
from typing import Any, ClassVar, Literal

from pydantic import BaseModel, ConfigDict

from .levels import Measured, db_to_linear, resolve_db

DbParam = float | str


def _n(value: float) -> str:
    """Format a plain number without trailing zeros."""
    return f"{value:g}"


def _linear(db: float) -> str:
    """Format a linear amplitude for filters that refuse dB."""
    return f"{db_to_linear(db):.5f}".rstrip("0").rstrip(".")


class Stage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stage_name: ClassVar[str]
    #: The one rate this stage can run at, where it only has one.
    required_rate: ClassVar[int | None] = None
    enabled: bool = True

    def filter(self, measured: Measured, models_dir: Path) -> str:
        raise NotImplementedError


class Highpass(Stage):
    stage_name: ClassVar[str] = "highpass"
    name: Literal["highpass"] = "highpass"
    f: float = 80.0

    def filter(self, measured: Measured, models_dir: Path) -> str:
        return f"highpass=f={_n(self.f)}"


class Afftdn(Stage):
    """Spectral subtraction. The right tool for a steady fan or HVAC."""

    stage_name: ClassVar[str] = "afftdn"
    name: Literal["afftdn"] = "afftdn"
    noise_floor_db: DbParam = "floor"
    reduction_db: float = 12.0
    track_noise: bool = True

    def filter(self, measured: Measured, models_dir: Path) -> str:
        floor = resolve_db(self.noise_floor_db, measured)
        clamped = min(-20.0, max(-80.0, floor))
        return (
            f"afftdn=nf={_n(clamped)}:nr={_n(self.reduction_db)}"
            f":tn={int(self.track_noise)}"
        )


class RNNoise(Stage):
    """Neural denoiser. Judges voice vs not-voice, so it can chew laughter."""

    stage_name: ClassVar[str] = "rnnoise"
    #: The models are trained at 48 kHz and arnndn will not run at anything else.
    required_rate: ClassVar[int] = 48_000
    name: Literal["rnnoise"] = "rnnoise"
    enabled: bool = False
    model: str = "lq"

    def filter(self, measured: Measured, models_dir: Path) -> str:
        model = models_dir / f"{self.model}.rnnn"
        if not model.is_file():
            raise ValueError(
                f"no RNNoise model at {model}; set $RNNOISE_MODELS to the "
                f"directory holding the .rnnn files, or pass --models"
            )
        return f"arnndn=m={model}"


class Gate(Stage):
    stage_name: ClassVar[str] = "gate"
    name: Literal["gate"] = "gate"
    threshold_db: DbParam = "floor+12"
    range_db: float = -40.0
    ratio: float = 6.0
    attack_ms: float = 5.0
    release_ms: float = 250.0

    def filter(self, measured: Measured, models_dir: Path) -> str:
        threshold = resolve_db(self.threshold_db, measured)
        return (
            f"agate=threshold={_linear(threshold)}:range={_linear(self.range_db)}"
            f":ratio={_n(self.ratio)}:attack={_n(self.attack_ms)}"
            f":release={_n(self.release_ms)}"
        )


class Band(BaseModel):
    model_config = ConfigDict(extra="forbid")

    f: float
    width: float = 1.0
    gain_db: float


class Eq(Stage):
    stage_name: ClassVar[str] = "eq"
    name: Literal["eq"] = "eq"
    enabled: bool = False
    bands: list[Band] = []

    def filter(self, measured: Measured, models_dir: Path) -> str:
        return ",".join(
            f"equalizer=f={_n(b.f)}:t=q:w={_n(b.width)}:g={_n(b.gain_db)}"
            for b in self.bands
        )


class Compressor(Stage):
    stage_name: ClassVar[str] = "compressor"
    name: Literal["compressor"] = "compressor"
    threshold_db: float = -18.0
    ratio: float = 3.0
    attack_ms: float = 5.0
    release_ms: float = 60.0

    def filter(self, measured: Measured, models_dir: Path) -> str:
        return (
            f"acompressor=threshold={_n(self.threshold_db)}dB:ratio={_n(self.ratio)}"
            f":attack={_n(self.attack_ms)}:release={_n(self.release_ms)}"
        )


class Deesser(Stage):
    stage_name: ClassVar[str] = "deesser"
    name: Literal["deesser"] = "deesser"
    intensity: float = 0.4
    frequency: float = 0.5
    max_reduction: float = 0.5

    def filter(self, measured: Measured, models_dir: Path) -> str:
        return (
            f"deesser=i={_n(self.intensity)}:f={_n(self.frequency)}"
            f":m={_n(self.max_reduction)}"
        )


REGISTRY: dict[str, type[Stage]] = {
    cls.stage_name: cls
    for cls in (Highpass, Afftdn, RNNoise, Gate, Eq, Compressor, Deesser)
}


def build_stage(spec: dict[str, Any]) -> Stage:
    spec = dict(spec)
    name = spec.get("name")
    if name not in REGISTRY:
        known = ", ".join(sorted(REGISTRY))
        raise ValueError(f"unknown stage {name!r}; available stages are: {known}")
    return REGISTRY[name](**spec)


def _check_rate(stages: list[Stage], target_rate: int) -> None:
    """Refuse a working rate a stage in this chain cannot run at."""
    for stage in stages:
        if stage.required_rate not in (None, target_rate):
            raise ValueError(
                f"{stage.stage_name} only runs at {stage.required_rate} Hz, but this "
                f"episode's working_rate_hz is {target_rate}; set it to "
                f"{stage.required_rate} or switch {stage.stage_name} off"
            )


def build_chain(
    specs: list[dict[str, Any]],
    measured: Measured,
    models_dir: Path,
    *,
    source_rate: int,
    target_rate: int,
) -> str:
    """The pass-2 filter graph: every enabled stage in order.

    A take already at the working rate is not resampled — converting 48 kHz to
    48 kHz is a no-op that costs nothing but says something untrue about the
    pipeline. A take at another rate is brought over first, because the stages
    downstream are configured against one rate and `rnnoise` only runs at 48 kHz.
    """
    stages = [s for s in (build_stage(spec) for spec in specs) if s.enabled]
    _check_rate(stages, target_rate)
    filters = [s.filter(measured, models_dir) for s in stages]
    head = [] if source_rate == target_rate else [f"aresample={target_rate}"]
    return ",".join([*head, *(f for f in filters if f)])
