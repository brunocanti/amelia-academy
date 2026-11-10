import pytest
from fastapi.testclient import TestClient

from amelia_academy import api, expander


class Stub:
    model = "stub"

    def __init__(self, text):
        self.text = text
        self.prompts = []

    def complete_json(self, prompt, schema, temperature=0.9):
        self.prompts.append(prompt)
        return {"text": self.text}


def test_a_draft_is_written_out_in_the_project_language():
    stub = Stub("Meu nome é Lia. Estudei compressão.")
    assert expander.expand(stub, "identity", "Lia, compressão", "pt-BR", "Specializes in compression") == stub.text
    assert "Portuguese" in stub.prompts[0] and "Lia, compressão" in stub.prompts[0] and "Specializes in compression" in stub.prompts[0]


def test_only_a_story_may_grow():
    story = Stub("I was built in 2024.")
    assert expander.expand(story, "identity", "I am Lia") == "I was built in 2024."
    answer = Stub("It reached 128 kbps.")
    with pytest.raises(ValueError, match="128"):
        expander.expand(answer, "answer", "It got good bitrates")
    assert "Do not add facts" in answer.prompts[0]


def test_numbers_from_the_draft_or_the_context_are_fine():
    assert expander.expand(Stub("It reached 128 kbps and 3 hops."), "answer", "128 kbps", context="The file says 3 hops")


def test_unchanged_expansion_is_retried_then_reported_as_nothing_to_add():
    class SameThenUseful(Stub):
        def complete_json(self, prompt, schema, temperature=0.9):
            self.prompts.append(prompt)
            return {"text": "Draft" if len(self.prompts) == 1 else "A fuller draft."}

    model = SameThenUseful("Draft")
    assert expander.expand(model, "identity", "Draft") == "A fuller draft."
    assert len(model.prompts) == 2


def test_unchanged_expansion_after_retry_reports_nothing_to_add():
    model = Stub("Draft")
    with pytest.raises(ValueError, match="Nothing to add"):
        expander.expand(model, "identity", "Draft")
    assert len(model.prompts) == 2


@pytest.mark.parametrize("field,text,result,reason", [
    ("quote", "x", "y", "unknown field"),
    ("answer", "   ", "y", "write something"),
    ("answer", "x", "", "wrote nothing"),
    ("answer", "x", "y" * (expander.MAX_CHARS + 1), "the limit"),
])
def test_a_bad_request_or_result_fails_visibly(field, text, result, reason):
    with pytest.raises(ValueError, match=reason):
        expander.expand(Stub(result), field, text)


def test_the_route_returns_a_suggestion_and_saves_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "DATA_DIR", tmp_path)
    monkeypatch.setattr(api, "DB_PATH", tmp_path / "academy.sqlite3")
    monkeypatch.setattr(api, "_conn", None)
    monkeypatch.setattr(api, "OllamaClient", lambda **kw: Stub("A clear text."))
    client = TestClient(api.app)
    r = client.post("/expand", json={"field": "card_intent", "text": "be clear", "model": "stub"})
    assert r.status_code == 200 and r.json() == {"text": "A clear text."}
    assert client.post("/expand", json={"field": "quote", "text": "x", "model": "stub"}).status_code == 422
