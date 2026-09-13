"""最终报告引用验证节点。"""

import json

from langchain_core.messages import HumanMessage

from deepscout.config import get_settings
from deepscout.graph.state import DeepScoutState
from deepscout.llm import get_chat_model
from deepscout.models.citation import CitationVerificationReport
from deepscout.models.result import Critique
from deepscout.prompts.citation import CITATION_VERIFIER_PROMPT


def _dump(value: object) -> str:
    if isinstance(value, list):
        value = [
            item.model_dump(mode="json") if hasattr(item, "model_dump") else item for item in value
        ]
    return json.dumps(value, ensure_ascii=False, indent=2, default=str)


def critique_from_verification(report: CitationVerificationReport) -> Critique:
    """把引用缺口转换成可被现有 Planner 消费的 Critique。"""
    return Critique(
        coverage_score=report.coverage_score,
        missing_aspects=report.unsupported_claims,
        conflicts=[],
        failed_task_ids=[],
        replan_required=report.requires_research,
        reasoning_summary="引用验证发现仍有关键事实缺少充分证据。",
    )


async def citation_verifier(state: DeepScoutState) -> dict:
    model = get_chat_model(get_settings().model_for("verifier"))
    structured = model.with_structured_output(CitationVerificationReport)
    prompt = CITATION_VERIFIER_PROMPT.format(
        report=state.get("final_report", ""),
        evidence=_dump(state.get("evidence_store", [])),
    )
    report = await structured.ainvoke([HumanMessage(content=prompt)])
    updates: dict[str, object] = {"citation_report": report}
    if report.requires_research:
        updates["critique"] = critique_from_verification(report)
    return updates
