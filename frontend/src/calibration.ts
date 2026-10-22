// Mirror of backend/lsg/output/curve.py for charts and live feedback.
import type { LedCalibration } from "./types";

export function lightnessToDuty(v: number, cal: LedCalibration): number {
  const x = Math.min(1, Math.max(0, v));
  if (cal.curve === "gamma") return x ** cal.gamma;
  const L = x * 100;
  return L <= 8 ? L / 903.3 : ((L + 16) / 116) ** 3;
}

/** PWM value (0..max_level) of a perceived grey level, as the LEDs will receive it. */
export function pwmOf(v: number, cal: LedCalibration): number {
  if (v <= cal.cutoff) return 0;
  const scaled = (v - cal.cutoff) / Math.max(1e-6, 1 - cal.cutoff);
  return cal.min_level + (cal.max_level - cal.min_level) * lightnessToDuty(scaled, cal);
}

/** Smallest perceived level that lands on a given PWM step. */
export function levelForPwm(pwm: number, cal: LedCalibration): number {
  let lo = 0,
    hi = 1;
  for (let i = 0; i < 40; i++) {
    const mid = (lo + hi) / 2;
    if (pwmOf(mid, cal) < pwm) lo = mid;
    else hi = mid;
  }
  return hi;
}

export const SERIES = ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300", "#9085e9", "#e66767"];
