import csv
from pathlib import Path
from xml.etree import ElementTree

import pytest
from pydantic import ValidationError

from deepscout.evaluation.models import (
    BenchmarkCase,
    BenchmarkCorpus,
    BenchmarkGoldRubric,
    BenchmarkRubricCriterion,
    BenchmarkSourcePolicy,
)
from deepscout.evaluation.quality import BenchmarkQualityPolicy, audit_benchmark_corpus
from deepscout.evaluation.quality_report import save_quality_report
from deepscout.evaluation.runner import load_corpus


def test_core_corpus_quality_audit_is_strictly_clean(tmp_path: Path):
    corpus = load_corpus("benchmarks/corpora/core.json")
    report = audit_benchmark_corpus(corpus)
    assert corpus.version == "1.3.0"
    assert len(corpus.cases) == 20
    assert report.passed is True
    assert report.error_count == 0
    assert report.warning_count == 0
    assert report.snapshot.topic_group_count == 7
    assert report.snapshot.freshness_case_count == 14
    assert report.snapshot.rubric_case_count == 20
    assert max(report.snapshot.topic_counts.values()) == 4
    assert report.snapshot.difficulty_counts == {"hard": 14, "medium": 6}

    paths = save_quality_report(corpus, report, tmp_path)
    for path in paths.values():
        assert path.exists()
    ElementTree.parse(paths["topic_chart"])
    ElementTree.parse(paths["difficulty_chart"])
    with paths["cases_csv"].open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 20
    assert all(row["preferred_domains"] for row in rows)
    assert all(row["required_points"] for row in rows)


def test_quality_audit_rejects_missing_policy_and_concentration():
    cases = [
        BenchmarkCase(
            case_id=f"case-{index}",
            query="fixture query",
            category="same",
            topic_group="same",
            difficulty="hard",
            expected_keywords=["a", "b", "c"],
        )
        for index in range(4)
    ]
    corpus = BenchmarkCorpus(name="bad", version="1", cases=cases)
    policy = BenchmarkQualityPolicy(min_cases=4, min_topic_groups=2)
    report = audit_benchmark_corpus(corpus, policy)
    codes = {issue.code for issue in report.issues}
    assert report.passed is False
    assert "missing_source_policy" in codes
    assert "missing_gold_rubric" in codes
    assert "topic_concentration" in codes
    assert "category_concentration" in codes
    assert "too_many_hard_cases" in codes


def test_source_policy_requires_freshness_window():
    with pytest.raises(ValidationError, match="max_age_days"):
        BenchmarkSourcePolicy(
            preferred_domains=["example.com"],
            primary_source_types=["official_docs"],
            freshness_required=True,
        )


def test_gold_rubric_requires_weights_sum_to_one():
    criteria = [
        BenchmarkRubricCriterion(criterion_id="a", description="a", weight=0.6),
        BenchmarkRubricCriterion(criterion_id="b", description="b", weight=0.3),
        BenchmarkRubricCriterion(criterion_id="c", description="c", weight=0.2),
    ]
    with pytest.raises(ValidationError, match="权重之和"):
        BenchmarkGoldRubric(
            required_points=["a", "b", "c"],
            criteria=criteria,
        )
