"""Level arithmetic: unit conversion, auto values, and gain match.

Config speaks dB throughout. ffmpeg does not — agate wants linear amplitude,
acompressor wants dB — so conversion lives here and stage classes call into it.
"""

import re
from dataclasses import dataclass

AUTO_VALUE = re.compile(r"^([a-z_]+)(?:\s*([+-])\s*([\d.]+))?$")
#: 20*log10(sqrt(2)) — how far a sine's peak sits above its RMS.
SINE_PEAK_OVER_RMS_DB = 3.0102999566398120
#: Fixed, not derived. Three dB under the -24 working level the clean step
#: brings takes to, which puts the tone's peak at -24 dBFS: plainly audible
#: against speech, nowhere near the peak ceiling, and not the loudest thing in
#: the episode. Change it here if the working level ever moves.
TONE_LEVEL_DB = -27.0
#: Delivery loudness for the mastered mixdown: the podcast baseline (Apple
#: Podcasts, AES TD1008). Unrelated to the working level, which takes keep.
TARGET_LUFS = -16.0
TRUE_PEAK_LIMIT_DB = -1.0
#: AES TD1008's tolerance around the target.
TARGET_TOLERANCE_LU = 1.0
#: Where the master's limiter sits: half a dB under the true-peak limit, for
#: the overshoot AAC and MP3 encoding add on top of it.
LIMITER_CEILING_DB = -1.5
#: How close a rendered master must come to the target before it is encoded.
#: The limiter pulls integrated loudness down as it works — two units on raw
#: speech — so the gain is corrected and the master rendered again until here.
MASTER_SETTLED_LU = 0.2


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


@dataclass(frozen=True)
class GainMatch:
    gain_db: float
    resulting_peak_db: float
    clamped: bool


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


def gain_match(
    measured: Measured, working_level_db: float, peak_ceiling_db: float
) -> GainMatch:
    """Constant gain bringing a take to the working level, clamped at the ceiling."""
    if measured.integrated_lufs is None or measured.true_peak_db is None:
        raise ValueError(
            "loudness has not been measured; gain match needs the post-chain pass"
        )

    wanted = working_level_db - measured.integrated_lufs
    peak_if_applied = measured.true_peak_db + wanted
    if peak_if_applied <= peak_ceiling_db:
        return GainMatch(gain_db=wanted, resulting_peak_db=peak_if_applied, clamped=False)

    allowed = peak_ceiling_db - measured.true_peak_db
    return GainMatch(gain_db=allowed, resulting_peak_db=peak_ceiling_db, clamped=True)


def master_gain(integrated_lufs: float) -> float:
    """Constant gain bringing a mixdown to the delivery loudness."""
    return TARGET_LUFS - integrated_lufs


def master_settled(integrated_lufs: float) -> bool:
    return abs(integrated_lufs - TARGET_LUFS) <= MASTER_SETTLED_LU


def meets_delivery(integrated_lufs: float, true_peak_db: float) -> bool:
    """Whether an encoded master lands on target and under the peak limit."""
    on_target = abs(integrated_lufs - TARGET_LUFS) <= TARGET_TOLERANCE_LU
    return on_target and true_peak_db <= TRUE_PEAK_LIMIT_DB
