"""Level arithmetic: unit conversion, auto values, and gain match.

Config speaks dB throughout. ffmpeg does not — agate wants linear amplitude,
acompressor wants dB — so conversion lives here and stage classes call into it.
"""

import re
from dataclasses import dataclass

AUTO_VALUE = re.compile(r"^([a-z_]+)(?:\s*([+-])\s*([\d.]+))?$")
#: 20*log10(sqrt(2)) — how far a sine's peak sits above its RMS.
SINE_PEAK_OVER_RMS_DB = 3.0102999566398120
#: Used where there is no episode to read a working level from. Three dB under
#: the default -24 working level: audible as a bleep without being the loudest
#: thing in the episode.
DEFAULT_TONE_LEVEL_DB = -27.0


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


def _resolve(value: float | str, references: dict[str, float], example: str) -> float:
    """Resolve a dB parameter that may be a number or an auto value.

    Auto values are a named reference with an optional offset, e.g. "floor+12"
    — read as "twelve dB above this take's noise floor". Which references are
    available depends on what is being resolved, so the caller supplies them.
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
            f"a reference like {example!r}"
        )

    name, sign, offset = match.groups()
    if name not in references:
        raise ValueError(
            f"unknown reference {name!r} in auto value; here you can use "
            f"{', '.join(sorted(references))}"
        )
    base = references[name]
    if offset is None:
        return base
    return base + (float(offset) if sign == "+" else -float(offset))


def resolve_db(value: float | str, measured: Measured) -> float:
    """Resolve a stage's dB parameter against what was measured for this take."""
    return _resolve(value, {"floor": measured.floor_db}, "floor+12")


def resolve_tone_db(value: float | str, working_level_db: float) -> float:
    """Resolve the tone level, which is placed against the working level.

    Deliberately not against the noise floor: the tone has to sit correctly
    with respect to the speech around it, and the speech is at the working
    level by the time anything gets spliced.
    """
    return _resolve(value, {"working": working_level_db}, "working-3")


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
