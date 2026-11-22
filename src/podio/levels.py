"""Level arithmetic: unit conversion, auto values, and delivery loudness.

Config speaks dB throughout. ffmpeg does not — agate wants linear amplitude,
acompressor wants dB — so conversion lives here and stage classes call into it.
"""

import re
from dataclasses import dataclass

AUTO_VALUE = re.compile(r"^([a-z_]+)(?:\s*([+-])\s*([\d.]+))?$")
#: 20*log10(sqrt(2)) — how far a sine's peak sits above its RMS.
SINE_PEAK_OVER_RMS_DB = 3.0102999566398120
#: Delivery loudness: the podcast baseline (Apple Podcasts, AES TD1008).
TARGET_LUFS = -16.0
TRUE_PEAK_LIMIT_DB = -1.0
#: Three dB under the delivery loudness, which puts the tone's peak on it:
#: plainly audible against speech, under the limiter's ceiling, and not the
#: loudest thing in the episode.
TONE_LEVEL_DB = TARGET_LUFS - 3.0
#: AES TD1008's tolerance around the target.
TARGET_TOLERANCE_LU = 1.0
#: Where the delivery limiter sits: half a dB under the true-peak limit, for
#: the overshoot AAC and MP3 encoding add on top of it.
LIMITER_CEILING_DB = -1.5
#: How close a leveled render must come to the target before it is used.
#: The limiter pulls integrated loudness down as it works — two units on raw
#: speech — so the gain is corrected and the audio rendered again until here.
SETTLED_LU = 0.2


@dataclass(frozen=True)
class Measured:
    """What analysis learned about one take.

    `floor_db` comes from the pre-chain pass and is what auto values resolve
    against. The loudness fields come from the post-chain pass and stay None
    until it has run.
    """

    floor_db: float
    integrated_lufs: float | None = None
    true_peak_db: float | None = None


def db_to_linear(db: float) -> float:
    return 10.0 ** (db / 20.0)


def resolve_db(value: float | str, measured: Measured) -> float:
    """Resolve a dB parameter that may be a number or an auto value.

    Auto values are a measurement reference with an optional offset, e.g.
    "floor+12" — read as "twelve dB above this take's noise floor".
    """
    if not isinstance(value, str):
        return float(value)

    text = value.replace(" ", "")
    try:
        return float(text)
    except ValueError:
        pass

    match = AUTO_VALUE.match(text)
    if not match:
        raise ValueError(
            f"cannot read {value!r} as a dB value; expected a number or "
            f"a reference like 'floor+12'"
        )

    name, sign, offset = match.groups()
    if name != "floor":
        raise ValueError(
            f"unknown reference {name!r} in auto value; only 'floor' is available"
        )
    base = measured.floor_db
    if offset is None:
        return base
    return base + (float(offset) if sign == "+" else -float(offset))


def tone_amplitude(tone_level_db: float, full_scale: int) -> int:
    """Peak sample value for a sine whose RMS is `tone_level_db` dBFS.

    A sine peaks 3.01 dB above its own RMS, so the level asked for is met by a
    wave that reaches higher than it — which is why this can clamp.
    """
    peak = db_to_linear(tone_level_db + SINE_PEAK_OVER_RMS_DB) * full_scale
    return min(full_scale, round(peak))


def delivery_gain(integrated_lufs: float) -> float:
    """Constant gain bringing audio to the delivery loudness."""
    return TARGET_LUFS - integrated_lufs


def delivery_settled(integrated_lufs: float) -> bool:
    return abs(integrated_lufs - TARGET_LUFS) <= SETTLED_LU


def meets_delivery(integrated_lufs: float, true_peak_db: float) -> bool:
    """Whether an encoded file lands on target and under the peak limit."""
    on_target = abs(integrated_lufs - TARGET_LUFS) <= TARGET_TOLERANCE_LU
    return on_target and true_peak_db <= TRUE_PEAK_LIMIT_DB
