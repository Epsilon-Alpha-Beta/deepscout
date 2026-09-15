"""为 DeepScout Ablation 实验规划 Case 数、power 与 detectable effect。"""

import argparse
from pathlib import Path

from deepscout.evaluation.ablation import load_ablation_matrix
from deepscout.evaluation.power import build_power_plan
from deepscout.evaluation.power_report import save_power_plan
from deepscout.evaluation.runner import load_corpus


def _parse_effect_sizes(raw: str) -> tuple[float, ...]:
    values = tuple(float(item.strip()) for item in raw.split(",") if item.strip())
    if not values or any(value <= 0.0 for value in values):
        raise argparse.ArgumentTypeError("effect sizes 必须是逗号分隔的正数。")
    return values


def main() -> None:
    parser = argparse.ArgumentParser(description="规划 DeepScout 消融实验样本量与近似 power。")
    parser.add_argument("--corpus", default="benchmarks/corpora/core.json")
    parser.add_argument("--matrix", default="benchmarks/ablations/core.json")
    parser.add_argument("--alpha", type=float, default=0.05)
    parser.add_argument("--target-power", type=float, default=0.8)
    parser.add_argument("--effect-sizes", type=_parse_effect_sizes, default=(0.2, 0.5, 0.8))
    parser.add_argument("--paired-std", type=float, default=None)
    parser.add_argument("--max-units", type=int, default=10000)
    parser.add_argument(
        "--output-dir", type=Path, default=Path("benchmark-results/power-plan-latest")
    )
    parser.add_argument("--validate-only", action="store_true")
    args = parser.parse_args()
    corpus = load_corpus(args.corpus)
    matrix = load_ablation_matrix(args.matrix)
    family_size = len(
        [profile for profile in matrix.profiles if profile.name != matrix.baseline_profile]
    )
    plan = build_power_plan(
        current_units=len(corpus.cases),
        family_size=family_size,
        alpha=args.alpha,
        target_power=args.target_power,
        effect_sizes=args.effect_sizes,
        paired_std=args.paired_std,
        max_units=args.max_units,
    )
    exact = plan.exact_resolution
    if args.validate_only:
        print(
            f"corpus={corpus.name} cases={len(corpus.cases)} family_size={family_size} "
            f"holm_reachable={str(exact.holm_reachable).lower()} "
            f"minimum_units={exact.minimum_units_for_holm} "
            f"mde_dz={plan.minimum_detectable_dz_at_current_units:.4f} status=valid"
        )
        return
    paths = save_power_plan(plan, args.output_dir)
    print(
        f"cases={len(corpus.cases)} family_size={family_size} "
        f"holm_reachable={exact.holm_reachable} json={paths['json']} markdown={paths['markdown']}"
    )


if __name__ == "__main__":
    main()
