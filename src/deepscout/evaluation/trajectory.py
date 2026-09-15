"""LangGraph updates → 低敏感 Benchmark 轨迹。"""

from collections import Counter
from collections.abc import Mapping
from time import monotonic
from typing import Any

from deepscout.evaluation.models import TrajectoryEvent


class TrajectoryRecorder:
    """只记录节点、时序和输出字段名，不记录模型正文或证据正文。"""

    def __init__(self) -> None:
        self._started_at = monotonic()
        self._events: list[TrajectoryEvent] = []

    @property
    def events(self) -> list[TrajectoryEvent]:
        return list(self._events)

    @property
    def node_visits(self) -> dict[str, int]:
        return dict(Counter(event.node for event in self._events))

    def record_update(self, update: Any) -> None:
        if not isinstance(update, Mapping):
            return
        for node, payload in update.items():
            if node == "__interrupt__":
                self._append("__interrupt__", [])
                continue
            keys = sorted(str(key) for key in payload) if isinstance(payload, Mapping) else []
            self._append(str(node), keys)

    def _append(self, node: str, output_keys: list[str]) -> None:
        self._events.append(
            TrajectoryEvent(
                sequence=len(self._events),
                node=node,
                elapsed_ms=round((monotonic() - self._started_at) * 1000.0, 3),
                output_keys=output_keys,
            )
        )
