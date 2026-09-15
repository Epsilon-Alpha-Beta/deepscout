"""Evidence Manager 节点。"""

from deepscout.config import get_settings
from deepscout.evidence.manager import build_claim_links, consolidate_evidence
from deepscout.graph.state import DeepScoutState


def evidence_manager(state: DeepScoutState, *, deduplicate: bool = True) -> dict:
    """归一化证据，并按 Graph 选项决定是否去重。"""
    settings = get_settings()
    evidence_store = consolidate_evidence(
        state.get("task_results", []),
        max_items=settings.max_evidence_items,
        deduplicate=deduplicate,
    )
    claim_links = build_claim_links(evidence_store)
    return {
        "evidence_store": evidence_store,
        "claim_links": claim_links,
    }
