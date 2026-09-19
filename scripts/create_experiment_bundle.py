"""创建或校验 DeepScout Experiment Bundle。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from deepscout.evaluation.experiment_bundle import (
    create_experiment_bundle,
    validate_experiment_bundle,
)


def _parse_extra(values: list[str]) -> dict[str, Path]:
    result: dict[str, Path] = {}
    for value in values:
        if "=" not in value:
            raise ValueError("--extra-artifact 格式必须为 role=path")
        role, path = value.split("=", 1)
        if not role or role in result:
            raise ValueError(f"无效或重复 artifact role: {role!r}")
        result[role] = Path(path)
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--validate", type=Path, default=None)
    parser.add_argument("--repeated", type=Path, default=None)
    parser.add_argument("--quality-aggregate", type=Path, default=None)
    parser.add_argument("--corpus", type=Path, default=Path("benchmarks/corpora/core.json"))
    parser.add_argument("--matrix", type=Path, default=Path("benchmarks/ablations/core.json"))
    parser.add_argument("--provider", default=None)
    parser.add_argument("--model", default=None)
    parser.add_argument("--experiment-id", default=None)
    parser.add_argument("--git-sha", default=None)
    parser.add_argument("--git-dirty", action="store_true")
    parser.add_argument("--config-json", default=None)
    parser.add_argument("--extra-artifact", action="append", default=[])
    parser.add_argument("--output-dir", type=Path, default=None)
    args = parser.parse_args()
    if args.validate is not None:
        report = validate_experiment_bundle(args.validate)
        print(
            f"valid={str(report.valid).lower()} checked={report.checked_artifacts} "
            f"errors={len(report.errors)}"
        )
        for error in report.errors:
            print(f"error={error}")
        return 0 if report.valid else 1
    if args.repeated is None or args.output_dir is None:
        parser.error("创建 bundle 需要 --repeated 与 --output-dir。")
    config = json.loads(args.config_json) if args.config_json else {}
    manifest = create_experiment_bundle(
        repeated_path=args.repeated,
        quality_aggregate_path=args.quality_aggregate,
        corpus_path=args.corpus,
        matrix_path=args.matrix,
        provider=args.provider,
        model=args.model,
        experiment_id=args.experiment_id,
        git_sha=args.git_sha,
        git_dirty=args.git_dirty if args.git_sha is not None else None,
        config=config,
        extra_artifacts=_parse_extra(args.extra_artifact),
        output_dir=args.output_dir,
    )
    print(
        f"experiment_id={manifest.experiment_id} artifacts={len(manifest.artifacts)} "
        f"git_sha={manifest.git_sha} dirty={str(manifest.git_dirty).lower()} "
        f"manifest={args.output_dir / 'manifest.json'}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
