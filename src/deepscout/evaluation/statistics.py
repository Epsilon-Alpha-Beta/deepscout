"""重复实验的确定性描述统计与 bootstrap 置信区间。"""

from __future__ import annotations

import hashlib
import random
import statistics
from collections.abc import Sequence

from pydantic import BaseModel, Field


class DistributionStatistics(BaseModel):
    """单个数值指标的重复实验统计量。"""

    count: int = Field(ge=0)
    mean: float
    std: float = Field(ge=0.0)
    median: float
    p50: float
    p95: float
    ci_low: float
    ci_high: float
    confidence_level: float = Field(gt=0.0, lt=1.0)


def percentile(values: Sequence[float], q: float) -> float:
    """使用线性插值计算 [0, 1] 分位数。"""
    if not values:
        raise ValueError("percentile 至少需要一个样本。")
    if not 0.0 <= q <= 1.0:
        raise ValueError("q 必须位于 [0, 1]。")
    ordered = sorted(float(value) for value in values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * q
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def stable_seed(base_seed: int, *parts: str) -> int:
    """从实验维度构造跨进程稳定 seed。"""
    payload = "|".join([str(base_seed), *parts]).encode("utf-8")
    digest = hashlib.sha256(payload).digest()
    return int.from_bytes(digest[:8], "big", signed=False)


def bootstrap_mean_ci(
    values: Sequence[float],
    *,
    confidence_level: float = 0.95,
    resamples: int = 2000,
    seed: int = 20260915,
) -> tuple[float, float]:
    """以确定性 percentile bootstrap 估计均值置信区间。"""
    if not values:
        raise ValueError("bootstrap 至少需要一个样本。")
    if not 0.0 < confidence_level < 1.0:
        raise ValueError("confidence_level 必须位于 (0, 1)。")
    if resamples < 1:
        raise ValueError("resamples 必须 >= 1。")
    numeric = [float(value) for value in values]
    if len(numeric) == 1:
        return numeric[0], numeric[0]

    rng = random.Random(seed)
    sample_size = len(numeric)
    means: list[float] = []
    for _ in range(resamples):
        sample = [numeric[rng.randrange(sample_size)] for _ in range(sample_size)]
        means.append(statistics.fmean(sample))

    alpha = (1.0 - confidence_level) / 2.0
    return percentile(means, alpha), percentile(means, 1.0 - alpha)


def summarize_distribution(
    values: Sequence[float],
    *,
    confidence_level: float = 0.95,
    resamples: int = 2000,
    seed: int = 20260915,
) -> DistributionStatistics:
    """计算 mean/std/median/p50/p95 与均值 bootstrap CI。"""
    numeric = [float(value) for value in values]
    if not numeric:
        raise ValueError("统计分布至少需要一个样本。")

    mean = statistics.fmean(numeric)
    std = statistics.stdev(numeric) if len(numeric) > 1 else 0.0
    median = statistics.median(numeric)
    ci_low, ci_high = bootstrap_mean_ci(
        numeric,
        confidence_level=confidence_level,
        resamples=resamples,
        seed=seed,
    )
    return DistributionStatistics(
        count=len(numeric),
        mean=mean,
        std=std,
        median=median,
        p50=percentile(numeric, 0.50),
        p95=percentile(numeric, 0.95),
        ci_low=ci_low,
        ci_high=ci_high,
        confidence_level=confidence_level,
    )
