import json
from types import SimpleNamespace

from agents.agents import evaluator_node


def test_evaluator_node_parses_structured_score_and_feedback(monkeypatch):
    fake_json = json.dumps({"score": 7, "feedback": "Good grasp of the basics, missed the light-independent reactions."})
    fake_response = SimpleNamespace(content=[SimpleNamespace(text=fake_json)])
    monkeypatch.setattr(
        "agents.agents.anthropic_client.messages.create",
        lambda **kwargs: fake_response,
    )

    state = {
        "chunks": ["Photosynthesis converts light energy into chemical energy."],
        "quiz_questions": ["What is photosynthesis?"],
        "user_answer": "It's how plants make food from sunlight.",
    }

    result = evaluator_node(state)

    assert result == {
        "score": 7,
        "feedback": "Good grasp of the basics, missed the light-independent reactions.",
    }


def test_evaluator_node_falls_back_on_malformed_json(monkeypatch):
    fake_response = SimpleNamespace(content=[SimpleNamespace(text="not valid json")])
    monkeypatch.setattr(
        "agents.agents.anthropic_client.messages.create",
        lambda **kwargs: fake_response,
    )

    state = {
        "chunks": ["Photosynthesis converts light energy into chemical energy."],
        "quiz_questions": ["What is photosynthesis?"],
        "user_answer": "It's how plants make food from sunlight.",
    }

    result = evaluator_node(state)

    assert result == {"score": 0, "feedback": "not valid json"}
