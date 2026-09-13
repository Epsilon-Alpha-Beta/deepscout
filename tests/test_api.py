from types import SimpleNamespace

from fastapi.testclient import TestClient
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command

from deepscout.agents.human_review import human_review
from deepscout.api.app import create_app
from deepscout.graph.state import DeepScoutState
from deepscout.runtime.checkpoint import memory_checkpointer


class FakeGraph:
    def __init__(self):
        self.last_input = None
        self.last_config = None

    async def ainvoke(self, input_value, config):
        self.last_input = input_value
        self.last_config = config
        return {"final_report": "fake report"}

    async def astream(self, input_value, config, *, stream_mode):
        self.last_input = input_value
        self.last_config = config
        assert stream_mode == "updates"
        yield {"writer": {"final_report": "fake report"}}

    async def aget_state(self, config):
        self.last_config = config
        return SimpleNamespace(next=(), values={"final_report": "fake report"})


def _client(graph: FakeGraph):
    return TestClient(create_app(graph=graph))


def test_health_and_research_json():
    graph = FakeGraph()
    with _client(graph) as client:
        assert client.get("/healthz").json() == {"status": "ok"}
        response = client.post(
            "/v1/research",
            json={"query": "test", "thread_id": "thread-json"},
        )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"
    assert body["final_report"] == "fake report"
    assert graph.last_config["configurable"]["thread_id"] == "thread-json"


def test_resume_uses_langgraph_command():
    graph = FakeGraph()
    with _client(graph) as client:
        response = client.post(
            "/v1/research/thread-resume/resume",
            json={"action": "approve"},
        )
    assert response.status_code == 200
    assert isinstance(graph.last_input, Command)
    assert graph.last_input.resume["action"] == "approve"


def test_revision_requires_feedback():
    with _client(FakeGraph()) as client:
        response = client.post(
            "/v1/research/thread-resume/resume",
            json={"action": "revise"},
        )
    assert response.status_code == 422


def test_sse_stream_contains_metadata_update_and_done():
    graph = FakeGraph()
    with _client(graph) as client:
        response = client.post(
            "/v1/research/stream",
            json={"query": "test", "thread_id": "thread-stream"},
        )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    text = response.text
    assert "event: metadata" in text
    assert "event: update" in text
    assert "event: done" in text


def test_thread_state_endpoint():
    graph = FakeGraph()
    with _client(graph) as client:
        response = client.get("/v1/research/thread-state")
    assert response.status_code == 200
    assert response.json()["values"]["final_report"] == "fake report"


def test_real_hitl_graph_interrupts_and_resumes_through_api():
    builder = StateGraph(DeepScoutState)
    builder.add_node("human_review", human_review)
    builder.add_edge(START, "human_review")
    builder.add_edge("human_review", END)
    graph = builder.compile(checkpointer=memory_checkpointer())

    with TestClient(create_app(graph=graph)) as client:
        first = client.post(
            "/v1/research",
            json={
                "query": "review this",
                "thread_id": "thread-real-hitl",
                "require_approval": True,
            },
        )
        assert first.status_code == 200
        assert first.json()["status"] == "interrupted"

        paused = client.get("/v1/research/thread-real-hitl")
        assert paused.status_code == 200
        assert paused.json()["next_nodes"] == ["human_review"]

        resumed = client.post(
            "/v1/research/thread-real-hitl/resume",
            json={"action": "approve"},
        )
        assert resumed.status_code == 200
        assert resumed.json()["status"] == "completed"

        finished = client.get("/v1/research/thread-real-hitl")
        assert finished.json()["next_nodes"] == []
