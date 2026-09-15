"""实验样本量、exact p-value 分辨率与近似 paired power 规划。"""

from __future__ import annotations

import math
from statistics import NormalDist

from pydantic import BaseModel, Field


class ExactResolutionPlan(BaseModel):
    units: int = Field(ge=1)
    family_size: int = Field(ge=1)
    alpha: float = Field(gt=0.0, lt=1.0)
    raw_minimum_two_sided_p: float = Field(gt=0.0, le=1.0)
    worst_case_holm_minimum_p: float = Field(gt=0.0, le=1.0)
    holm_reachable: bool
    minimum_units_for_holm: int = Field(ge=1)


class PowerScenario(BaseModel):
    effect_size_dz: float = Field(gt=0.0)
    approximate_power_at_current_units: float = Field(ge=0.0, le=1.0)
    required_units_for_target_power: int = Field(ge=2)


class PowerCurvePoint(BaseModel):
    units: int = Field(ge=2)
    effect_size_dz: float = Field(gt=0.0)
    approximate_power: float = Field(ge=0.0, le=1.0)


class ExperimentPowerPlan(BaseModel):
    current_units: int = Field(ge=1)
    family_size: int = Field(ge=1)
    alpha: float = Field(gt=0.0, lt=1.0)
    conservative_adjusted_alpha: float = Field(gt=0.0, lt=1.0)
    target_power: float = Field(gt=0.0, lt=1.0)
    planning_method: str = "paired_normal_bonferroni_approximation"
    exact_resolution: ExactResolutionPlan
    minimum_detectable_dz_at_current_units: float = Field(gt=0.0)
    paired_std: float | None = Field(default=None, gt=0.0)
    minimum_detectable_absolute_effect: float | None = None
    scenarios: list[PowerScenario]
    power_curve: list[PowerCurvePoint]


def minimum_units_for_exact_holm(alpha: float, family_size: int) -> int:
    if not 0.0 < alpha < 1.0:
        raise ValueError("alpha 必须位于 (0, 1)。")
    if family_size < 1:
        raise ValueError("family_size 必须 >= 1。")
    return max(1, math.ceil(math.log2(2.0 * family_size / alpha)))


def exact_resolution_plan(units: int, family_size: int, alpha: float) -> ExactResolutionPlan:
    if units < 1:
        raise ValueError("units 必须 >= 1。")
    minimum = minimum_units_for_exact_holm(alpha, family_size)
    raw = min(1.0, 2.0 / (2**units))
    holm = min(1.0, family_size * raw)
    return ExactResolutionPlan(
        units=units,
        family_size=family_size,
        alpha=alpha,
        raw_minimum_two_sided_p=raw,
        worst_case_holm_minimum_p=holm,
        holm_reachable=holm <= alpha,
        minimum_units_for_holm=minimum,
    )


def approximate_paired_power(
    units: int,
    effect_size_dz: float,
    *,
    alpha: float,
    family_size: int,
) -> float:
    if units < 2:
        return 0.0
    if effect_size_dz <= 0.0:
        return alpha / family_size
    adjusted = alpha / family_size
    normal = NormalDist()
    critical = normal.inv_cdf(1.0 - adjusted / 2.0)
    noncentral = abs(effect_size_dz) * math.sqrt(units)
    power = 1.0 - normal.cdf(critical - noncentral) + normal.cdf(-critical - noncentral)
    return min(1.0, max(0.0, power))


def required_units_for_power(
    effect_size_dz: float,
    target_power: float,
    *,
    alpha: float,
    family_size: int,
    max_units: int = 10000,
) -> int:
    if effect_size_dz <= 0.0:
        raise ValueError("effect_size_dz 必须 > 0。")
    if not 0.0 < target_power < 1.0:
        raise ValueError("target_power 必须位于 (0, 1)。")
    for units in range(2, max_units + 1):
        if (
            approximate_paired_power(units, effect_size_dz, alpha=alpha, family_size=family_size)
            >= target_power
        ):
            return units
    raise ValueError("max_units 内无法达到目标 power。")


def minimum_detectable_dz(
    units: int,
    target_power: float,
    *,
    alpha: float,
    family_size: int,
) -> float:
    if units < 2:
        raise ValueError("units 必须 >= 2 才能规划近似 power。")
    low, high = 0.0, 1.0
    while (
        approximate_paired_power(units, high, alpha=alpha, family_size=family_size) < target_power
    ):
        high *= 2.0
        if high > 100.0:
            raise ValueError("无法在合理效应量范围内达到目标 power。")
    for _ in range(80):
        middle = (low + high) / 2.0
        if (
            approximate_paired_power(units, middle, alpha=alpha, family_size=family_size)
            >= target_power
        ):
            high = middle
        else:
            low = middle
    return high


def build_power_plan(
    *,
    current_units: int,
    family_size: int = 5,
    alpha: float = 0.05,
    target_power: float = 0.8,
    effect_sizes: tuple[float, ...] = (0.2, 0.5, 0.8),
    paired_std: float | None = None,
    max_units: int = 10000,
) -> ExperimentPowerPlan:
    if current_units < 2:
        raise ValueError("current_units 必须 >= 2。")
    if paired_std is not None and paired_std <= 0.0:
        raise ValueError("paired_std 必须 > 0。")
    if not effect_sizes or any(effect <= 0.0 for effect in effect_sizes):
        raise ValueError("effect_sizes 必须是非空正数序列。")

    resolution = exact_resolution_plan(current_units, family_size, alpha)
    mde = minimum_detectable_dz(
        current_units,
        target_power,
        alpha=alpha,
        family_size=family_size,
    )
    scenarios = [
        PowerScenario(
            effect_size_dz=effect,
            approximate_power_at_current_units=approximate_paired_power(
                current_units, effect, alpha=alpha, family_size=family_size
            ),
            required_units_for_target_power=required_units_for_power(
                effect,
                target_power,
                alpha=alpha,
                family_size=family_size,
                max_units=max_units,
            ),
        )
        for effect in effect_sizes
    ]
    curve_max = max(
        current_units, *(scenario.required_units_for_target_power for scenario in scenarios)
    )
    curve_max = min(max_units, max(curve_max, resolution.minimum_units_for_holm, 12))
    units_grid = sorted({2, 4, 6, 8, 10, 12, current_units, curve_max})
    if curve_max > 12:
        step = max(1, curve_max // 8)
        units_grid.extend(range(step, curve_max + 1, step))
        units_grid = sorted({units for units in units_grid if 2 <= units <= curve_max})
    curve = [
        PowerCurvePoint(
            units=units,
            effect_size_dz=effect,
            approximate_power=approximate_paired_power(
                units, effect, alpha=alpha, family_size=family_size
            ),
        )
        for effect in effect_sizes
        for units in units_grid
    ]
    return ExperimentPowerPlan(
        current_units=current_units,
        family_size=family_size,
        alpha=alpha,
        conservative_adjusted_alpha=alpha / family_size,
        target_power=target_power,
        exact_resolution=resolution,
        minimum_detectable_dz_at_current_units=mde,
        paired_std=paired_std,
        minimum_detectable_absolute_effect=(mde * paired_std if paired_std is not None else None),
        scenarios=scenarios,
        power_curve=curve,
    )
