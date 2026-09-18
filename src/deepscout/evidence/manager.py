"""确定性的证据规范化、去重与 Claim-Evidence 映射。"""

import hashlib
import re
from collections import defaultdict
from datetime import UTC, datetime
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from deepscout.evidence.metadata import classify_source_url
from deepscout.models.evidence import ClaimEvidenceLink, ManagedEvidence
from deepscout.models.result import TaskResult

_TRACKING_KEYS = {
    "fbclid",
    "gclid",
    "mc_cid",
    "mc_eid",
}


def canonicalize_url(url: str) -> str:
    """移除 fragment/常见追踪参数，并稳定化 query 顺序。"""
    parts = urlsplit(url)
    query = []
    for key, value in parse_qsl(parts.query, keep_blank_values=True):
        lowered = key.lower()
        if lowered.startswith("utm_") or lowered in _TRACKING_KEYS:
            continue
        query.append((key, value))
    query.sort()
    path = parts.path or "/"
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, urlencode(query), ""))


def content_fingerprint(content: str) -> str:
    """对归一化文本生成稳定 SHA-256 指纹。"""
    normalized = re.sub(r"\s+", " ", content).strip().lower()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _evidence_id(canonical_url: str, content_hash: str, *, salt: str = "") -> str:
    raw = f"{canonical_url}|{content_hash}|{salt}".encode()
    return "ev_" + hashlib.sha256(raw).hexdigest()[:12]


def consolidate_evidence(
    results: list[TaskResult],
    *,
    max_items: int,
    deduplicate: bool = True,
) -> list[ManagedEvidence]:
    """扁平化成功任务的证据；默认按 URL/内容指纹去重。"""
    merged: dict[str, ManagedEvidence] = {}
    content_index: dict[str, str] = {}
    collected: list[ManagedEvidence] = []
    occurrence = 0

    for result in results:
        if result.status != "completed":
            continue
        for item in result.evidence:
            canonical = canonicalize_url(str(item.url))
            fingerprint = content_fingerprint(item.content)
            key = canonical
            existing_key = key if key in merged else content_index.get(fingerprint)

            if deduplicate and existing_key is not None:
                current = merged[existing_key]
                current.duplicate_count += 1
                current.claims = sorted(set(current.claims).union(item.claims))
                if current.source_class == "unknown":
                    current.source_class = (
                        item.source_class
                        if item.source_class != "unknown"
                        else classify_source_url(canonical)
                    )
                if current.published_at is None and item.published_at is not None:
                    current.published_at = item.published_at
                if item.retrieved_at is not None and (
                    current.retrieved_at is None or item.retrieved_at > current.retrieved_at
                ):
                    current.retrieved_at = item.retrieved_at
                if item.relevance_score is not None:
                    current.relevance_score = max(
                        current.relevance_score or 0.0,
                        item.relevance_score,
                    )
                continue

            occurrence += 1
            managed = ManagedEvidence(
                evidence_id=_evidence_id(
                    canonical,
                    fingerprint,
                    salt="" if deduplicate else str(occurrence),
                ),
                title=item.title,
                url=str(item.url),
                canonical_url=canonical,
                source_host=urlsplit(canonical).netloc,
                content=item.content,
                content_hash=fingerprint,
                source_type=item.source_type,
                source_class=(
                    item.source_class
                    if item.source_class != "unknown"
                    else classify_source_url(canonical)
                ),
                published_at=item.published_at,
                retrieved_at=item.retrieved_at or datetime.now(UTC),
                relevance_score=item.relevance_score,
                claims=sorted(set(item.claims)),
            )
            if deduplicate:
                merged[key] = managed
                content_index[fingerprint] = key
            else:
                collected.append(managed)

            current_size = len(merged) if deduplicate else len(collected)
            if current_size >= max_items:
                break
        current_size = len(merged) if deduplicate else len(collected)
        if current_size >= max_items:
            break

    return list(merged.values()) if deduplicate else collected


def _claim_key(claim: str) -> str:
    normalized = re.sub(r"\s+", " ", claim).strip().lower()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:12]


def build_claim_links(evidence: list[ManagedEvidence]) -> list[ClaimEvidenceLink]:
    """根据 Researcher 提取的 claims 建立 Claim-Evidence 映射。"""
    mapping: dict[str, dict[str, object]] = defaultdict(
        lambda: {"claim": "", "evidence_ids": set()}
    )
    for item in evidence:
        for claim in item.claims:
            clean = re.sub(r"\s+", " ", claim).strip()
            if not clean:
                continue
            key = _claim_key(clean)
            mapping[key]["claim"] = clean
            evidence_ids = mapping[key]["evidence_ids"]
            assert isinstance(evidence_ids, set)
            evidence_ids.add(item.evidence_id)

    return [
        ClaimEvidenceLink(
            claim_id=f"cl_{key}",
            claim=str(value["claim"]),
            evidence_ids=sorted(value["evidence_ids"]),
        )
        for key, value in sorted(mapping.items())
    ]
