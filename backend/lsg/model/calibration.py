"""Hardware calibration: how perceived brightness maps to LED PWM values, and power figures.

Shows and effects work with *perceived* brightness (0.5 looks half as bright as 1.0). LEDs
are driven by PWM duty, which the eye perceives very non-linearly: the steps 1 -> 2 -> 3
are huge jumps while 254 -> 255 is invisible. The calibration curve converts perceived
values into PWM values per LED type and makes sure that dim values stay visible
(`min_level`) instead of being rounded away.
"""

from typing import Literal

from pydantic import BaseModel, Field

from lsg.model.fixture import LedType

CurveKind = Literal["cie", "gamma"]
Dithering = Literal["none", "spatial", "temporal"]
WhiteMode = Literal["off", "min", "color"]


class LedCalibration(BaseModel):
    curve: CurveKind = Field(default="cie", description="cie = CIE 1931 lightness (recommended), gamma = power curve")
    gamma: float = Field(default=2.4, ge=1.0, le=4.0)
    min_level: int = Field(default=1, ge=1, le=64, description="lowest PWM value a lit LED gets")
    max_level: int = Field(default=255, ge=16, le=255, description="PWM value for full brightness")
    cutoff: float = Field(default=0.004, ge=0.0, le=0.2, description="perceived level below which the LED is off")
    white_balance: tuple[float, float, float] = Field(default=(1.0, 1.0, 1.0), description="per channel scale 0..1")
    dithering: Dithering = "none"
    # RGBW strips: how much of a colour is moved to the white LED
    white_mode: WhiteMode = "color"
    white_color: str = Field(default="#ffe6c8", description="colour of the white LED (warm white ~ #ffd8b0)")
    # power
    ma_per_channel: float = Field(default=20.0, ge=1.0, le=100.0, description="mA of one channel at PWM 255")
    ma_idle: float = Field(default=1.0, ge=0.0, le=10.0, description="mA per LED when dark")


def default_calibration() -> dict[LedType, LedCalibration]:
    return {
        LedType.WS2812B: LedCalibration(),
        LedType.SK6812: LedCalibration(ma_per_channel=18.0),
        LedType.SK6812_RGBW: LedCalibration(ma_per_channel=18.0),
    }


class PowerSettings(BaseModel):
    total_budget_ma: float | None = Field(default=None, ge=100, description="shared power supply limit for all controllers")
    volts: float = Field(default=5.0, ge=3.0, le=48.0)
