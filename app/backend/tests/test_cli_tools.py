"""Models reached by command line. The tools are stand-in scripts: this covers our handling of what they say, not the models."""

import json
import os
import stat
import time

import pytest
from fastapi.testclient import TestClient

from amelia_academy import api, cli_tools, console, runs
from amelia_academy.cli_tools import CliClient, _mismatch, _strict, provider_of, tool_of
from amelia_academy.llm import LLMError, OllamaClient

SCHEMA = {"type": "object", "properties": {"answer": {"type": "string"}, "note": {"type": "string"}}, "required": ["answer"]}


@pytest.fixture
def bin_dir(tmp_path, monkeypatch):
    folder = tmp_path / "bin"
    folder.mkdir()
    monkeypatch.setenv("PATH", f"{folder}{os.pathsep}/usr/bin{os.pathsep}/bin")
    monkeypatch.setattr(cli_tools, "EXTRA_PATH", ())
    cli_tools.forget_models()
    yield folder
    cli_tools.forget_models()


def tool(folder, name, script):
    path = folder / name
    path.write_text("#!/bin/sh\n" + script)
    path.chmod(path.stat().st_mode | stat.S_IEXEC)


def says(folder, name, *events, code=0):
    lines = "\n".join(json.dumps(event) for event in events)
    tool(folder, name, f"cat > /dev/null\ncat <<'EOF'\n{lines}\nEOF\nexit {code}\n")


CLAUDE_OK = ({"type": "stream_event", "event": {"delta": {"type": "input_json_delta", "partial_json": '{"answer"'}}},
             {"type": "result", "is_error": False, "result": "", "structured_output": {"answer": "yes"},
              "usage": {"input_tokens": 2, "cache_creation_input_tokens": 1000, "output_tokens": 30}})
CODEX_OK = ({"type": "item.completed", "item": {"type": "agent_message", "text": '{"answer":"yes"}'}},
            {"type": "turn.completed", "usage": {"input_tokens": 1400, "output_tokens": 30}})
AGY_OK = ({"event": "step_update", "step_update": {"step_type": "agent_response", "text_delta": '{"answer":"yes"}'}},
          {"event": "result", "result": {"status": "SUCCESS", "response": '{"answer":"yes"}\n',
                                         "usage": {"input_tokens": 1400, "output_tokens": 30}}})


@pytest.mark.parametrize("name,command,events,tokens", [
    ("claude-cli:h", "claude", CLAUDE_OK, 1002),
    ("codex-cli:l", "codex", CODEX_OK, 1400),
    ("agy-cli:g", "agy", AGY_OK, 1400),
])
def test_each_tool_answers_in_the_agreed_shape_and_its_tokens_are_counted(bin_dir, name, command, events, tokens):
    says(bin_dir, command, *events)
    console.clear()
    assert CliClient(name).complete_json("q", SCHEMA) == {"answer": "yes"}
    line = console.snapshot()["lines"][-1]
    assert (line["prompt_tokens"], line["output_tokens"], line["error"]) == (tokens, 30, "")


def test_a_call_runs_with_tools_off_in_an_empty_folder(bin_dir, tmp_path):
    seen = tmp_path / "seen"
    tool(bin_dir, "claude", f'printf "%s\\n" "$@" > {seen}.args\npwd > {seen}.pwd\nls -A > {seen}.ls\ncat > {seen}.stdin\n'
         f"cat <<'EOF'\n{json.dumps(CLAUDE_OK[1])}\nEOF\n")
    CliClient("claude-cli:h").complete_json("the passage", SCHEMA, images=["aGk="])
    args = (tmp_path / "seen.args").read_text().splitlines()
    assert args[args.index("--tools") + 1] == ""
    assert (tmp_path / "seen.ls").read_text() == ""
    assert not os.path.exists((tmp_path / "seen.pwd").read_text().strip())  # and gone afterwards
    content = json.loads((tmp_path / "seen.stdin").read_text())["message"]["content"]
    assert content[0]["source"]["data"] == "aGk=" and content[1]["text"] == "the passage"


@pytest.mark.parametrize("name,command,event", [
    ("codex-cli:l", "codex", {"type": "item.started", "item": {"type": "command_execution", "command": "cat secret"}}),
    ("agy-cli:g", "agy", {"event": "step_update", "step_update": {"step_type": "tool", "tool_name": "read_file"}}),
])
def test_a_model_reaching_for_a_tool_stops_the_call(bin_dir, name, command, event):
    says(bin_dir, command, event, *(CODEX_OK if command == "codex" else AGY_OK))
    with pytest.raises(LLMError, match="tried to use"):
        CliClient(name).complete_json("q", SCHEMA)


def test_what_the_tool_says_went_wrong_reaches_the_person(bin_dir):
    says(bin_dir, "codex", {"type": "turn.failed", "error": {"message": "The model is not supported"}}, code=1)
    with pytest.raises(LLMError, match="Codex: The model is not supported"):
        CliClient("codex-cli:old").complete_json("q", SCHEMA)
    says(bin_dir, "claude", {"type": "result", "is_error": True, "result": "Not logged in", "usage": {}}, code=1)
    with pytest.raises(LLMError, match="Claude: Not logged in"):
        CliClient("claude-cli:h").complete_json("q", SCHEMA)
    tool(bin_dir, "agy", "echo boom >&2\nexit 3\n")
    with pytest.raises(LLMError, match="boom"):
        CliClient("agy-cli:g").complete_json("q", SCHEMA)


def test_a_reply_outside_the_shape_or_empty_fails_visibly(bin_dir):
    says(bin_dir, "codex", {"type": "item.completed", "item": {"type": "agent_message", "text": '{"note":"x"}'}}, CODEX_OK[1])
    with pytest.raises(LLMError, match="reply has no answer"):
        CliClient("codex-cli:l").complete_json("q", SCHEMA)
    says(bin_dir, "codex", CODEX_OK[1])
    with pytest.raises(LLMError, match="returned nothing"):
        CliClient("codex-cli:l").complete_json("q", SCHEMA)


def test_a_missing_tool_is_a_clear_failure(bin_dir):
    with pytest.raises(LLMError, match="could not start"):
        CliClient("agy-cli:g").complete("q")


def test_a_quiet_tool_is_killed_at_the_time_limit(bin_dir, tmp_path):
    tool(bin_dir, "agy", f"echo $$ > {tmp_path}/pid\nsleep 30\n")
    started = time.monotonic()
    with pytest.raises(LLMError, match="timed out"):
        CliClient("agy-cli:g", timeout=0.5).complete("q")
    assert time.monotonic() - started < 10
    with pytest.raises(ProcessLookupError):
        os.kill(int((tmp_path / "pid").read_text()), 0)


def test_stop_reaches_a_quiet_tool_and_kills_it(bin_dir, tmp_path):
    pid = tmp_path / "pid"
    tool(bin_dir, "codex", f"echo $$ > {pid}\nsleep 30\n")
    entry = runs.launch("p", "test", "stop-cli", "t", {}, lambda: CliClient("codex-cli:l").complete("q"))
    for _ in range(100):
        if pid.exists() and pid.read_text().strip():
            break
        time.sleep(0.05)
    entry["stopping"] = True
    entry["thread"].join(10)
    assert entry["status"] == "stopped"
    with pytest.raises(ProcessLookupError):
        os.kill(int(pid.read_text()), 0)


def test_antigravity_is_asked_for_the_shape_in_words_because_its_schema_flag_fills_fields_with_the_prompt(bin_dir, tmp_path):
    seen = tmp_path / "args"
    tool(bin_dir, "agy", f'printf "%s\\n" "$@" > {seen}\ncat <<\'EOF\'\n{json.dumps(AGY_OK[1])}\nEOF\n')
    assert CliClient("agy-cli:g").complete_json("the passage", SCHEMA) == {"answer": "yes"}
    args = seen.read_text()
    assert "--json-schema" not in args
    assert "-p=the passage" in args and cli_tools.AGY_SHAPE in args and json.dumps(SCHEMA) in args


def test_antigravity_ignores_what_its_schema_flag_filled_in(bin_dir):
    says(bin_dir, "agy", {"event": "result", "result": {"status": "SUCCESS", "response": '{"answer":"right"}',
                                                        "structured_output": {"answer": "wrong"}, "usage": {}}})
    assert CliClient("agy-cli:g").complete_json("q", SCHEMA) == {"answer": "right"}


def test_a_reply_wrapped_in_a_code_fence_is_read_only_when_json_was_asked_for(bin_dir):
    fenced = '```json\n{"answer":"yes"}\n```\n'
    says(bin_dir, "agy", {"event": "result", "result": {"status": "SUCCESS", "response": fenced, "usage": {}}})
    assert CliClient("agy-cli:g").complete_json("q", SCHEMA) == {"answer": "yes"}
    assert CliClient("agy-cli:g").complete("q") == fenced


def test_what_goes_wrong_names_the_model_without_its_tool_prefix(bin_dir):
    says(bin_dir, "agy", {"event": "result", "result": {"status": "SUCCESS", "response": "not json", "usage": {}}})
    with pytest.raises(LLMError) as failure:
        CliClient("agy-cli:g").complete_json("q", SCHEMA)
    assert "Antigravity g" in str(failure.value) and "agy-cli" not in str(failure.value)


def test_a_tool_that_cannot_see_says_so_before_any_call(bin_dir):
    with pytest.raises(LLMError, match="cannot read images"):
        CliClient("agy-cli:g").complete_json("q", SCHEMA, images=["aGk="])


def test_codex_gets_a_closed_schema_and_the_reply_is_checked_against_the_original():
    closed = _strict({"type": "array", "items": SCHEMA})["items"]
    assert closed["required"] == ["answer", "note"] and closed["additionalProperties"] is False
    assert SCHEMA["required"] == ["answer"]


@pytest.mark.parametrize("value,schema,found", [
    ({"a": 1}, {"properties": {"a": {"type": "string"}}}, "reply.a is not a string"),
    ({"a": ["x", 2]}, {"properties": {"a": {"items": {"type": "string"}}}}, "reply.a[1] is not a string"),
    ({"a": "z"}, {"properties": {"a": {"enum": ["x"]}}}, "reply.a is not one of the allowed values"),
    ({"a": True}, {"properties": {"a": {"type": "integer"}}}, "reply.a is not a integer"),
    ({"a": 1.5}, {"properties": {"a": {"type": "number"}}}, ""),
])
def test_the_shape_check(value, schema, found):
    assert _mismatch(value, schema) == found


def test_the_name_says_who_runs_it():
    assert tool_of("gemma4:12b") is None and tool_of("") is None and tool_of(None) is None
    assert provider_of("gemma4:12b") == "ollama" and provider_of("codex-cli:gpt") == "codex-cli"
    assert isinstance(api.client_for("gemma4:12b"), OllamaClient)
    assert api.client_for("claude-cli:claude-haiku-5-5").slug == "claude-haiku-5-5"
    assert api.vision_client("agy-cli:g") is None and api.vision_client("codex-cli:l").model == "codex-cli:l"


@pytest.fixture
def client():
    return TestClient(api.app)


def signed_in_tools(folder):
    tool(folder, "claude", """echo '{"loggedIn": true}'\n""")
    tool(folder, "codex", """[ "$1" = login ] && exit 0\necho '{"models":[{"slug":"luna","display_name":"Luna","visibility":"list"},{"slug":"x","visibility":"hide"}]}'\n""")
    tool(folder, "agy", "echo 'Fetching available models...'\nprintf 'gem\\tGem Flash\\n'\n")


def test_the_list_holds_what_each_signed_in_tool_offers(bin_dir):
    signed_in_tools(bin_dir)
    found, problems = cli_tools.available_models()
    names = [m["name"] for m in found]
    assert "claude-cli:claude-haiku-5-5" in names and "codex-cli:luna" in names and "agy-cli:gem" in names
    assert "codex-cli:x" not in names and problems == []
    assert next(m for m in found if m["name"] == "agy-cli:gem")["notice"].startswith("Sends your files' text to Google")


def test_a_tool_not_signed_in_is_named_and_one_not_installed_is_not(bin_dir):
    tool(bin_dir, "agy", "exit 1\n")
    found, problems = cli_tools.available_models()
    assert found == [] and problems == ["Antigravity is not signed in. Run agy in a terminal."]


def test_the_default_stays_on_this_computer_and_a_stopped_ollama_does_not_hide_the_tools(client, bin_dir, monkeypatch):
    signed_in_tools(bin_dir)
    monkeypatch.setattr(api, "installed_models", lambda _url: [{"name": "local:1", "size": 1, "vision": False}])
    body = client.get("/models").json()
    assert body["default"] == "local:1" and body["models"][0]["online"] is False and len(body["models"]) > 1

    def down(_url):
        raise LLMError("ollama unreachable")
    monkeypatch.setattr(api, "installed_models", down)
    body = client.get("/models").json()
    assert body["default"] == "" and body["models"] and "Ollama is not running" in body["problems"][0]


def test_with_no_ollama_and_no_tool_the_list_is_a_clear_503(client, bin_dir, monkeypatch):
    def down(_url):
        raise LLMError("ollama unreachable")
    monkeypatch.setattr(api, "installed_models", down)
    assert client.get("/models").status_code == 503
