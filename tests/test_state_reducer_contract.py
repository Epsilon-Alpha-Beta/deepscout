from typing import get_type_hints

from deepscout.graph.state import DeepScoutState


def test_task_results_has_reducer_metadata():
    hints = get_type_hints(DeepScoutState, include_extras=True)
    assert "task_results" in hints
    assert "Annotated" in str(hints["task_results"])
