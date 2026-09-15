"""可复现 Graph 结构选项，主要用于 Phase 4 消融实验。"""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class GraphOptions:
    """不依赖 Provider 的确定性 Graph 结构开关。"""

    citation_feedback_enabled: bool = True
    evidence_dedup_enabled: bool = True
