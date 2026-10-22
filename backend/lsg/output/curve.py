"""Perceived brightness -> PWM duty, per LED calibration."""

import numpy as np

from lsg.model.calibration import LedCalibration
from lsg.render.colors import parse_color


def lightness_to_duty(v: np.ndarray, cal: LedCalibration) -> np.ndarray:
    """Perceived lightness 0..1 -> linear light (duty) 0..1."""
    v = np.clip(v, 0.0, 1.0)
    if cal.curve == "gamma":
        return v**cal.gamma
    lightness = v * 100.0  # CIE 1931 L*
    return np.where(lightness <= 8.0, lightness / 903.3, ((lightness + 16.0) / 116.0) ** 3)


def duty_to_lightness(d: np.ndarray, cal: LedCalibration) -> np.ndarray:
    d = np.clip(d, 0.0, 1.0)
    if cal.curve == "gamma":
        return d ** (1.0 / cal.gamma)
    return np.where(d <= 8.0 / 903.3, d * 903.3, 116.0 * np.cbrt(d) - 16.0) / 100.0


def to_pwm(v: np.ndarray, cal: LedCalibration) -> np.ndarray:
    """Perceived RGB (n, 3) -> PWM floats (n, 3) in 0..max_level.

    Values above `cutoff` start at `min_level`, so dim colours stay visible; the curve
    is rescaled so that the cutoff maps exactly to min_level (no jump).
    """
    v = np.asarray(v, dtype=np.float32)
    lit = v > cal.cutoff
    scaled = (v - cal.cutoff) / max(1e-6, 1.0 - cal.cutoff)
    duty = lightness_to_duty(scaled, cal) * np.asarray(cal.white_balance, dtype=np.float32)
    pwm = cal.min_level + (cal.max_level - cal.min_level) * duty
    return np.where(lit, pwm, 0.0).astype(np.float32)


def pwm_of_level(level: float, cal: LedCalibration) -> float:
    """PWM value of a single perceived grey level (for charts and docs)."""
    return float(to_pwm(np.array([[level, level, level]]), cal.model_copy(update={"white_balance": (1, 1, 1)}))[0, 0])


def white_rgb(cal: LedCalibration) -> np.ndarray:
    """RGB duty the white LED corresponds to (normalised so its max channel is 1)."""
    c = lightness_to_duty(parse_color(cal.white_color), cal.model_copy(update={"curve": "cie"}))
    return c / max(float(c.max()), 1e-6)


def extract_white(pwm: np.ndarray, cal: LedCalibration) -> tuple[np.ndarray, np.ndarray]:
    """Split RGB PWM into (RGB, W) for RGBW LEDs according to the white mode."""
    if cal.white_mode == "off":
        return pwm, np.zeros(len(pwm), np.float32)
    if cal.white_mode == "min":
        w = pwm.min(axis=1)
        return pwm - w[:, None], w
    wc = white_rgb(cal)
    # largest amount of the white LED's colour that fits inside the requested colour
    w = np.min(pwm / np.maximum(wc, 1e-6), axis=1)
    w = np.minimum(w, cal.max_level)
    return np.maximum(pwm - w[:, None] * wc, 0.0), w
