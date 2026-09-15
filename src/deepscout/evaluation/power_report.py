"""实验 power / detectable-effect 规划报告。"""

from __future__ import annotations

import csv
from pathlib import Path

from deepscout.evaluation.power import ExperimentPowerPlan


def render_power_markdown(plan: ExperimentPowerPlan) -> str:
    exact = plan.exact_resolution
    lines = [
        "# DeepScout Experiment Power Plan",
        "",
        f"- Current independent Case units: {plan.current_units}",
        f"- Hypothesis family size: {plan.family_size}",
        f"- Alpha: {plan.alpha:.3f}",
        f"- Conservative planning alpha: {plan.conservative_adjusted_alpha:.5f}",
        f"- Target power: {plan.target_power:.1%}",
        f"- Method: {plan.planning_method}",
        "",
        "## Exact sign-flip resolution",
        "",
        f"- Raw minimum two-sided p: {exact.raw_minimum_two_sided_p:.6g}",
        f"- Worst-case Holm minimum p: {exact.worst_case_holm_minimum_p:.6g}",
        f"- Holm reachable: {exact.holm_reachable}",
        f"- Minimum independent units for Holm reachability: {exact.minimum_units_for_holm}",
    ]
    lines.extend(
        [
            "",
            "## Approximate paired-normal planning",
            "",
            "Holm power 没有简单闭式解；这里使用 Bonferroni `alpha / family_size` "
            "作为保守规划近似。",
            "结果用于实验设计，不替代真实 permutation/Wilcoxon 分析。",
            "",
            "| Cohen dz | Power @ current N | Required N @ target power |",
            "| ---: | ---: | ---: |",
        ]
    )
    for scenario in plan.scenarios:
        lines.append(
            f"| {scenario.effect_size_dz:.3f} | "
            f"{scenario.approximate_power_at_current_units:.1%} | "
            f"{scenario.required_units_for_target_power} |"
        )
    lines.extend(
        [
            "",
            f"Minimum detectable Cohen dz at current N: "
            f"**{plan.minimum_detectable_dz_at_current_units:.3f}**",
        ]
    )
    if plan.minimum_detectable_absolute_effect is not None:
        lines.append(
            "Minimum detectable absolute paired effect: "
            f"**{plan.minimum_detectable_absolute_effect:.4g}** "
            f"(paired std={plan.paired_std:.4g})"
        )
    lines.extend(["", "See `power_curve.csv` and `charts/power_curve.svg` for the full curve."])
    return "\n".join(lines).rstrip() + "\n"


def write_sample_size_csv(plan: ExperimentPowerPlan, path: Path) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=(
                "effect_size_dz",
                "approximate_power_at_current_units",
                "required_units_for_target_power",
            ),
        )
        writer.writeheader()
        for scenario in plan.scenarios:
            writer.writerow(scenario.model_dump())


def write_power_curve_csv(plan: ExperimentPowerPlan, path: Path) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=("units", "effect_size_dz", "approximate_power"),
        )
        writer.writeheader()
        for point in plan.power_curve:
            writer.writerow(point.model_dump())


def render_power_curve_svg(plan: ExperimentPowerPlan) -> str:
    width, height = 980, 560
    left, right, top, bottom = 80, 40, 60, 70
    plot_w = width - left - right
    plot_h = height - top - bottom
    max_units = max(point.units for point in plan.power_curve)
    effects = sorted({point.effect_size_dz for point in plan.power_curve})
    dash_patterns = ("", "8 4", "2 4", "10 3 2 3")
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="white"/>',
        '<text x="24" y="34" font-family="sans-serif" font-size="22" font-weight="600">'
        "Approximate paired power curves</text>",
    ]
    y_target = top + (1.0 - plan.target_power) * plot_h
    parts.append(
        f'<line x1="{left}" y1="{y_target:.1f}" x2="{width - right}" y2="{y_target:.1f}" '
        'stroke="#b91c1c" stroke-dasharray="5 4"/>'
    )
    for index, effect in enumerate(effects):
        points = sorted(
            (point for point in plan.power_curve if point.effect_size_dz == effect),
            key=lambda point: point.units,
        )
        coords = []
        for point in points:
            x = left + (point.units - 2) / max(1, max_units - 2) * plot_w
            y = top + (1.0 - point.approximate_power) * plot_h
            coords.append(f"{x:.1f},{y:.1f}")
        dash = dash_patterns[index % len(dash_patterns)]
        dash_attr = f' stroke-dasharray="{dash}"' if dash else ""
        parts.append(
            f'<polyline points="{" ".join(coords)}" fill="none" stroke="#334155" '
            f'stroke-width="2.5"{dash_attr}/>'
        )
        parts.append(
            f'<text x="{width - right - 140}" y="{top + 22 * index}" font-family="sans-serif" '
            f'font-size="12">dz={effect:.2f}</text>'
        )
    parts.extend(
        [
            f'<line x1="{left}" y1="{top}" x2="{left}" y2="{height - bottom}" stroke="#111827"/>',
            f'<line x1="{left}" y1="{height - bottom}" x2="{width - right}" '
            f'y2="{height - bottom}" stroke="#111827"/>',
            f'<text x="{width / 2:.0f}" y="{height - 20}" text-anchor="middle" '
            'font-family="sans-serif" font-size="13">Independent Case units</text>',
            f'<text x="20" y="{height / 2:.0f}" transform="rotate(-90 20 '
            f'{height / 2:.0f})" text-anchor="middle" font-family="sans-serif" '
            'font-size="13">Power</text>',
            f'<text x="{width - right - 5}" y="{y_target - 6:.1f}" text-anchor="end" '
            f'font-family="sans-serif" font-size="11">target {plan.target_power:.0%}</text>',
            "</svg>",
        ]
    )
    return "\n".join(parts) + "\n"


def save_power_plan(plan: ExperimentPowerPlan, output_dir: str | Path) -> dict[str, Path]:
    directory = Path(output_dir)
    charts = directory / "charts"
    charts.mkdir(parents=True, exist_ok=True)
    paths = {
        "json": directory / "plan.json",
        "markdown": directory / "plan.md",
        "sample_sizes_csv": directory / "sample_sizes.csv",
        "power_curve_csv": directory / "power_curve.csv",
        "power_curve_svg": charts / "power_curve.svg",
    }
    paths["json"].write_text(plan.model_dump_json(indent=2) + "\n", encoding="utf-8")
    paths["markdown"].write_text(render_power_markdown(plan), encoding="utf-8")
    write_sample_size_csv(plan, paths["sample_sizes_csv"])
    write_power_curve_csv(plan, paths["power_curve_csv"])
    paths["power_curve_svg"].write_text(render_power_curve_svg(plan), encoding="utf-8")
    return paths
