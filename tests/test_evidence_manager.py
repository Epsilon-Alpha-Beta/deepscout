from deepscout.evidence.manager import (
    build_claim_links,
    canonicalize_url,
    consolidate_evidence,
)
from deepscout.models.evidence import Evidence
from deepscout.models.result import TaskResult


def _result(task_id: str, evidence: list[Evidence]) -> TaskResult:
    return TaskResult(
        task_id=task_id,
        status="completed",
        summary="ok",
        evidence=evidence,
    )


def test_canonicalize_url_removes_tracking_and_fragment():
    url = "https://EXAMPLE.com/a?utm_source=x&b=2&a=1#section"
    assert canonicalize_url(url) == "https://example.com/a?a=1&b=2"


def test_consolidate_merges_same_url():
    first = Evidence(
        title="A",
        url="https://example.com/page",
        content="first body",
        relevance_score=0.6,
        claims=["Claim A"],
    )
    second = Evidence(
        title="A2",
        url="https://example.com/page",
        content="second body",
        relevance_score=0.9,
        claims=["Claim B"],
    )
    store = consolidate_evidence([_result("T1", [first]), _result("T2", [second])], max_items=10)
    assert len(store) == 1
    assert store[0].duplicate_count == 2
    assert store[0].relevance_score == 0.9
    assert store[0].claims == ["Claim A", "Claim B"]


def test_same_content_different_urls_is_deduplicated():
    a = Evidence(title="A", url="https://a.example/x", content="same body")
    b = Evidence(title="B", url="https://b.example/y", content="same body")
    store = consolidate_evidence([_result("T1", [a, b])], max_items=10)
    assert len(store) == 1
    assert store[0].duplicate_count == 2


def test_claim_links_collect_multiple_evidence_ids():
    a = Evidence(title="A", url="https://a.example/x", content="body a", claims=["Claim X"])
    b = Evidence(title="B", url="https://b.example/y", content="body b", claims=["Claim X"])
    store = consolidate_evidence([_result("T1", [a, b])], max_items=10)
    links = build_claim_links(store)
    assert len(links) == 1
    assert len(links[0].evidence_ids) == 2
