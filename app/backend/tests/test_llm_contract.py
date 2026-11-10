"""Structured-output contract of the Ollama client. HTTP is stubbed: these tests cover our handling, not the model."""

import json

import httpx
import pytest

from amelia_academy import console, workshop
from amelia_academy.llm import FIGURE_MAX_TOKENS, MAX_TOKENS, LLMError, OllamaClient


class Streamed:
    """What httpx.stream hands back: the whole body as one line is enough for these tests."""
    status_code = 200
    text = ""

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def read(self):
        return b""

    def iter_lines(self):
        yield json.dumps(self.json())


class FakeResponse(Streamed):
    def __init__(self, content):
        self._content = content

    def json(self):
        return {"message": {"content": self._content}}


def client_returning(monkeypatch, content):
    sent = {}

    def fake_stream(method, url, json=None, timeout=None):  # noqa: A002 - mirrors httpx.post
        sent["payload"] = json
        return FakeResponse(content)

    monkeypatch.setattr(httpx, "stream", fake_stream)
    return OllamaClient(model="m"), sent


def test_schema_is_sent_as_ollama_format(monkeypatch):
    client, sent = client_returning(monkeypatch, json.dumps({"items": []}))
    client.complete_json("p", workshop.SAMPLE_SCHEMA, temperature=0.2)
    assert sent["payload"]["format"] == workshop.SAMPLE_SCHEMA
    assert sent["payload"]["options"]["temperature"] == 0.2


def test_free_text_call_sends_no_format(monkeypatch):
    client, sent = client_returning(monkeypatch, "hello")
    client.complete("p")
    assert "format" not in sent["payload"]


def test_broken_json_fails_visibly_instead_of_being_repaired(monkeypatch):
    client, _ = client_returning(monkeypatch, '{"items": [{"user_message": "a"')
    with pytest.raises(LLMError, match="structured-output contract"):
        client.complete_json("p", workshop.SAMPLE_SCHEMA)


def test_non_object_reply_is_rejected(monkeypatch):
    client, _ = client_returning(monkeypatch, "[1, 2]")
    with pytest.raises(LLMError, match="expected an object"):
        client.complete_json("p", workshop.SAMPLE_SCHEMA)


READING = json.dumps({"visible_text": "label", "reading": "A chart."})


def figure_client(monkeypatch, replies):
    """Each reply is (done_reason, content); returns the client and the options of every call."""
    sent, queue = [], list(replies)

    class Reply(Streamed):
        def __init__(self, done_reason, content):
            self.body = {"done_reason": done_reason, "message": {"content": content}}

        def json(self):
            return self.body

    def fake_stream(method, url, json=None, timeout=None):  # noqa: A002 - mirrors httpx.post
        sent.append(json["options"])
        return Reply(*queue.pop(0))

    monkeypatch.setattr(httpx, "stream", fake_stream)
    return OllamaClient(model="m"), sent


def test_a_normal_figure_reading_is_capped_and_has_no_repeat_penalty(monkeypatch):
    client, sent = figure_client(monkeypatch, [("stop", READING)])
    assert client.read_figure(b"png")["reading"] == "A chart."
    assert sent == [{"temperature": 0.1, "num_predict": FIGURE_MAX_TOKENS}]


def test_a_runaway_figure_reading_is_retried_with_a_repeat_penalty(monkeypatch):
    client, sent = figure_client(monkeypatch, [("length", '{"visible_text": "MLS\\nMLS\\n'), ("stop", READING)])
    assert client.read_figure(b"png")["visible_text"] == "label"
    assert len(sent) == 2 and sent[1]["repeat_penalty"] > 1 and sent[1]["num_predict"] == FIGURE_MAX_TOKENS


def test_a_figure_that_runs_away_twice_gets_a_reading_without_transcription(monkeypatch):
    client, sent = figure_client(monkeypatch, [("length", "{"), ("length", "{"), ("stop", json.dumps({"reading": "A graph."}))])
    assert client.read_figure(b"png") == {"visible_text": "", "reading": "A graph."}
    assert len(sent) == 3 and "repeat_penalty" not in sent[2]


def test_a_figure_that_runs_away_every_time_fails_with_the_reason(monkeypatch):
    client, sent = figure_client(monkeypatch, [("length", "{")] * 3)
    with pytest.raises(LLMError, match="kept repeating itself"):
        client.read_figure(b"png")
    assert len(sent) == 3


def test_other_calls_have_no_cap_and_ignore_done_reason(monkeypatch):
    client, sent = figure_client(monkeypatch, [("length", "hello")])
    assert client.complete("p") == "hello"
    assert sent == [{"temperature": 0.9}]


def test_every_call_reaches_the_console_with_agent_and_tokens(monkeypatch):
    console.clear()

    class Counted(FakeResponse):
        def json(self):
            return {**super().json(), "prompt_eval_count": 11, "eval_count": 7}

    monkeypatch.setattr(httpx, "stream", lambda method, url, json=None, timeout=None: Counted('{"text": "ok"}'))
    with console.acting("text_expander"):
        OllamaClient(model="m").complete_json("asked", {"type": "object"})
    state = console.snapshot()
    line = state["lines"][0]
    assert (line["agent"], line["prompt_tokens"], line["output_tokens"], line["error"]) == ("text_expander", 11, 7, "")
    assert "prompt" not in line  # the whole text comes only when a line is opened
    assert console.line(line["seq"])["prompt"] == "asked"
    assert not state["running"]
    agent = next(a for a in state["agents"] if a["name"] == "text_expander")
    assert (agent["nickname"], agent["calls"], agent["problems"]) == ("Fermento", 1, 0)


def test_a_failed_call_and_a_broken_reply_count_as_problems(monkeypatch):
    console.clear()

    def down(method, url, json=None, timeout=None):
        raise httpx.ConnectError("no")

    monkeypatch.setattr(httpx, "stream", down)
    with console.acting("passage_reader"), pytest.raises(LLMError):
        OllamaClient(model="m").complete_json("asked", {"type": "object"})
    monkeypatch.setattr(httpx, "stream", lambda method, url, json=None, timeout=None: FakeResponse("not json"))
    with console.acting("passage_reader"), pytest.raises(LLMError):
        OllamaClient(model="m").complete_json("asked", {"type": "object"})
    state = console.snapshot()
    assert not state["running"]
    assert next(a for a in state["agents"] if a["name"] == "passage_reader")["problems"] == 2


def test_an_agent_outside_the_group_is_a_bug():
    with pytest.raises(KeyError), console.acting("nobody"):
        pass


def test_every_structured_reply_is_capped(monkeypatch):
    client, sent = client_returning(monkeypatch, '{"a": 1}')
    client.complete_json("p", {"type": "object"})
    assert sent["payload"]["options"]["num_predict"] == MAX_TOKENS


def test_the_reply_shows_in_the_console_while_it_is_written(monkeypatch):
    console.clear()
    seen = []

    class Pieces(Streamed):
        def iter_lines(self):
            yield json.dumps({"message": {"content": '{"a":'}})
            seen.append(console.snapshot()["running"][0])
            yield ""
            yield json.dumps({"message": {"content": " 1}"}, "done": True, "done_reason": "stop", "eval_count": 2})

    monkeypatch.setattr(httpx, "stream", lambda method, url, json=None, timeout=None: Pieces())
    with console.acting("passage_reader"):
        assert OllamaClient(model="m").complete_json("p", {"type": "object"}) == {"a": 1}
    assert (seen[0]["text"], seen[0]["tokens"], seen[0]["agent"]) == ('{"a":', 1, "passage_reader")
    assert not console.snapshot()["running"]
    assert console.snapshot()["lines"][0]["output_tokens"] == 2


def test_a_stream_that_never_ends_still_hits_the_time_limit(monkeypatch):
    console.clear()

    class Endless(Streamed):
        def iter_lines(self):
            while True:
                yield json.dumps({"message": {"content": "x"}})

    monkeypatch.setattr(httpx, "stream", lambda method, url, json=None, timeout=None: Endless())
    with pytest.raises(LLMError, match="timed out"):
        OllamaClient(model="m", timeout=0.01).complete("p")
    assert not console.snapshot()["running"]


def test_a_call_finishing_after_a_poll_still_reaches_that_page():
    console.clear()
    call = console.begin("m", "asked")
    seen = console.snapshot()["last_seq"]
    console.end(call, reply="replied")
    assert [line["text"] for line in console.snapshot(seen)["lines"]] == ["replied"]
