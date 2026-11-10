"""Models reached through a tool someone already has signed in: Claude, Codex, Antigravity. Always the command line, never a provider's API.

The name of a model says who runs it: `codex-cli:gpt-6-luna`. A name without one of these prefixes is an Ollama model, so what
is already saved keeps working, and resuming a run finds its tool from the name alone.

A file's text is untrusted, and these tools are agents that can act. So each call runs in an empty folder deleted afterwards,
with every tool off where the command allows it. Where it does not (Codex, Antigravity) the tool is held to read-only or sandboxed, and
the call is stopped the moment the model reaches for a tool: writing pairs from a passage never needs one.

What a tool cannot honour is dropped on purpose: temperature, repeat penalty and the output cap have no flag on these commands,
so a runaway reply ends at the time limit, not at a token count.
"""

import base64
import json
import os
import queue
import shutil
import subprocess
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Callable

from . import console, runs
from .llm import LLMError, ModelClient

SYSTEM_PROMPT = "Do exactly what the user asks, using only what the message gives you."
LIST_TIMEOUT = 20
LIST_KEPT_SECONDS = 120
# A server started outside a shell may not have these on its PATH.
EXTRA_PATH = ("/opt/homebrew/bin", "/usr/local/bin", os.path.expanduser("~/.local/bin"))


@dataclass
class Reply:
    """What a tool has said so far. `tool_use` stops the call."""
    text: str = ""
    prompt_tokens: int = 0
    output_tokens: int = 0
    error: str = ""
    tool_use: str = ""
    finished: bool = False
    written: list[str] = field(default_factory=list)


def _strict(schema: dict) -> dict:
    """Codex takes only closed objects where every field is required."""
    if not isinstance(schema, dict):
        return schema
    closed = {key: _strict(value) if key in ("items", "additionalProperties") else value for key, value in schema.items()}
    if "properties" in schema:
        closed["properties"] = {name: _strict(part) for name, part in schema["properties"].items()}
        closed["required"] = list(schema["properties"])
        closed["additionalProperties"] = False
    return closed


def _unfenced(text: str) -> str:
    """A model asked for JSON in words may still wrap it in a code fence."""
    bare = text.strip()
    if bare.startswith("```") and bare.endswith("```") and "\n" in bare:
        return bare[bare.index("\n") + 1:-3].strip()
    return bare


def _mismatch(value, schema: dict, where: str = "reply") -> str:
    """Why a value does not fit the schema, or nothing. Ollama enforces this itself; here a tool's word is not taken for it."""
    kinds = {"object": dict, "array": list, "string": str, "boolean": bool, "number": (int, float), "integer": int}
    expected = schema.get("type")
    if expected in kinds and (not isinstance(value, kinds[expected]) or (expected != "boolean" and isinstance(value, bool))):
        return f"{where} is not a {expected}"
    if "enum" in schema and value not in schema["enum"]:
        return f"{where} is not one of the allowed values"
    if isinstance(value, dict):
        for name in schema.get("required", []):
            if name not in value:
                return f"{where} has no {name}"
        for name, part in schema.get("properties", {}).items():
            if name in value and (found := _mismatch(value[name], part, f"{where}.{name}")):
                return found
    if isinstance(value, list) and "items" in schema:
        for i, item in enumerate(value):
            if found := _mismatch(item, schema["items"], f"{where}[{i}]"):
                return found
    return ""


# --- Claude ---

def _claude_command(slug: str, prompt: str, schema: dict | None, images: list[str], _files: str) -> tuple[list[str], str]:
    argv = ["claude", "-p", "--model", slug, "--tools", "", "--system-prompt", SYSTEM_PROMPT, "--setting-sources", "",
            "--disable-slash-commands", "--strict-mcp-config", "--no-session-persistence", "--verbose",
            "--include-partial-messages", "--input-format", "stream-json", "--output-format", "stream-json"]
    if schema is not None:
        argv += ["--json-schema", json.dumps(schema)]
    pictures = [{"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": image}} for image in images]
    message = {"role": "user", "content": [*pictures, {"type": "text", "text": prompt}]}
    return argv, json.dumps({"type": "user", "message": message}) + "\n"


def _claude_event(event: dict, reply: Reply) -> None:
    if event.get("type") == "stream_event":
        delta = (event.get("event") or {}).get("delta") or {}
        reply.written.append(delta.get("text") or delta.get("partial_json") or "")
    elif event.get("type") == "result":
        usage = event.get("usage") or {}
        reply.prompt_tokens = sum(usage.get(key) or 0 for key in ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"))
        reply.output_tokens = usage.get("output_tokens") or 0
        reply.finished = True
        if event.get("is_error"):
            reply.error = str(event.get("result") or event.get("subtype") or "it stopped with an error")
        elif event.get("structured_output") is not None:
            reply.text = json.dumps(event["structured_output"], ensure_ascii=False)
        else:
            reply.text = str(event.get("result") or "")


def _claude_models() -> tuple[list[dict], str]:
    done = subprocess.run([_found("claude"), "auth", "status"], capture_output=True, text=True, timeout=LIST_TIMEOUT, stdin=subprocess.DEVNULL)
    try:
        signed_in = bool(json.loads(done.stdout).get("loggedIn"))
    except ValueError:
        signed_in = False
    if not signed_in:
        return [], "Claude is not signed in. Run claude in a terminal."
    return [{"slug": slug, "label": label} for slug, label in (
        ("claude-haiku-5-5", "Claude Haiku 5.5"), ("claude-sonnet-5-5", "Claude Sonnet 5.5"), ("claude-opus-5-5", "Claude Opus 5.5"))], ""


# --- Codex ---

# Its own steps, not tools. Anything else it starts is the model acting.
CODEX_QUIET_ITEMS = {"agent_message", "reasoning", "error", "todo_list"}


def _codex_command(slug: str, prompt: str, schema: dict | None, images: list[str], files: str) -> tuple[list[str], str]:
    argv = ["codex", "exec", "-", "-m", slug, "--sandbox", "read-only", "--ephemeral", "--skip-git-repo-check",
            "--ignore-user-config", "--ignore-rules", "--json"]
    if schema is not None:
        path = os.path.join(files, "schema.json")
        with open(path, "w", encoding="utf-8") as out:
            json.dump(_strict(schema), out)
        argv += ["--output-schema", path]
    for i, image in enumerate(images):
        path = os.path.join(files, f"image{i}.png")
        with open(path, "wb") as out:
            out.write(base64.b64decode(image))
        argv += ["-i", path]
    return argv, prompt


def _codex_event(event: dict, reply: Reply) -> None:
    kind = event.get("type")
    if kind in ("item.started", "item.completed"):
        item = event.get("item") or {}
        if item.get("type") not in CODEX_QUIET_ITEMS:
            reply.tool_use = str(item.get("type"))
        elif item.get("type") == "agent_message" and kind == "item.completed":
            reply.text = str(item.get("text") or "")
            reply.written.append(reply.text)
    elif kind == "turn.completed":
        usage = event.get("usage") or {}
        reply.prompt_tokens = usage.get("input_tokens") or 0  # counts what was cached too
        reply.output_tokens = usage.get("output_tokens") or 0
        reply.finished = True
    elif kind == "turn.failed":
        reply.error = str((event.get("error") or {}).get("message") or "it stopped with an error")
    elif kind == "error":
        reply.error = str(event.get("message") or "it stopped with an error")


def _codex_models() -> tuple[list[dict], str]:
    status = subprocess.run([_found("codex"), "login", "status"], capture_output=True, text=True, timeout=LIST_TIMEOUT, stdin=subprocess.DEVNULL)
    if status.returncode != 0:
        return [], "Codex is not signed in. Run codex login in a terminal."
    done = subprocess.run([_found("codex"), "debug", "models"], capture_output=True, text=True, timeout=LIST_TIMEOUT, stdin=subprocess.DEVNULL)
    try:
        listed = json.loads(done.stdout).get("models") or []
    except ValueError:
        return [], "Codex did not list its models."
    return [{"slug": m["slug"], "label": m.get("display_name") or m["slug"]} for m in listed if m.get("slug") and m.get("visibility") == "list"], ""


# --- Antigravity ---

# Its --json-schema is not used. It fills the fields without the model understanding them: `question` came back holding the
# prompt and `answer` the whole reply, a shape that passes every check. Asked in plain words, the same model answers correctly.
AGY_SHAPE = "Reply with only one JSON object, no other text and no code fences, matching this JSON schema:"


def _agy_command(slug: str, prompt: str, schema: dict | None, _images: list[str], _files: str, timeout: float = 600.0) -> tuple[list[str], str]:
    argv = ["agy", "--model", slug, "--output-format", "stream-json", "--sandbox", "--disable-slash-commands", "--print-timeout", f"{int(timeout)}s"]
    if schema is not None:
        prompt = f"{prompt}\n\n{AGY_SHAPE}\n{json.dumps(schema)}"
    return [*argv, f"-p={prompt}"], ""


def _agy_event(event: dict, reply: Reply) -> None:
    if event.get("event") == "step_update":
        step = event.get("step_update") or {}
        if step.get("step_type") == "tool":
            reply.tool_use = str(step.get("tool_name") or "tool")
        elif step.get("step_type") == "agent_response":
            reply.written.append(step.get("text_delta") or "")
    elif event.get("event") == "result":
        result = event.get("result") or {}
        usage = result.get("usage") or {}
        reply.prompt_tokens = (usage.get("input_tokens") or 0) + (usage.get("cache_read_tokens") or 0)
        reply.output_tokens = (usage.get("output_tokens") or 0) + (usage.get("thinking_tokens") or 0)
        reply.finished = True
        if result.get("status") != "SUCCESS":
            reply.error = str(result.get("error") or result.get("status") or "it stopped with an error")
        else:
            reply.text = str(result.get("response") or "")


def _agy_models() -> tuple[list[dict], str]:
    done = subprocess.run([_found("agy"), "models"], capture_output=True, text=True, timeout=LIST_TIMEOUT, stdin=subprocess.DEVNULL)
    if done.returncode != 0:
        return [], "Antigravity is not signed in. Run agy in a terminal."
    rows = [line.split("\t") for line in done.stdout.splitlines() if "\t" in line]
    return [{"slug": row[0].strip(), "label": row[1].strip()} for row in rows if row[0].strip()], ""


@dataclass(frozen=True)
class Tool:
    prefix: str
    name: str
    command: str
    company: str
    plan: str
    sees: bool  # passes images on, tried on a picture with text
    build: Callable
    read: Callable
    models: Callable


TOOLS = (
    Tool("claude-cli", "Claude", "claude", "Anthropic", "Claude", True, _claude_command, _claude_event, _claude_models),
    Tool("codex-cli", "Codex", "codex", "OpenAI", "ChatGPT", True, _codex_command, _codex_event, _codex_models),
    # Print mode has no documented way to pass an image.
    Tool("agy-cli", "Antigravity", "agy", "Google", "Antigravity", False, _agy_command, _agy_event, _agy_models),
)


def tool_of(model: str | None) -> Tool | None:
    prefix = (model or "").split(":", 1)[0]
    return next((tool for tool in TOOLS if tool.prefix == prefix), None)


def provider_of(model: str | None) -> str:
    tool = tool_of(model)
    return tool.prefix if tool else "ollama"


def _found(command: str) -> str:
    return shutil.which(command, path=os.pathsep.join([os.environ.get("PATH", ""), *EXTRA_PATH])) or command


class CliClient(ModelClient):
    def __init__(self, model: str, timeout: float = 600.0):
        self.tool = tool_of(model)
        if self.tool is None:
            raise LLMError(f"no tool runs {model}")
        self.model = model
        self.slug = model.split(":", 1)[1]
        self.timeout = timeout

    @property
    def shown(self) -> str:
        return f"{self.tool.name} {self.slug}"

    def _chat(self, prompt: str, temperature: float, schema: dict | None = None,
              images: list[str] | None = None, allow_empty: bool = False, options: dict | None = None) -> str:
        if images and not self.tool.sees:
            raise LLMError(f"{self.tool.name} cannot read images")
        runs.check()
        call = console.begin(self.model, prompt)
        try:
            reply = self._run(prompt, schema, images or [], call)
        except LLMError as exc:
            console.end(call, error=str(exc))
            raise
        except runs.Stopped:
            console.end(call, stopped=True)
            raise
        if schema is not None:
            reply.text = _unfenced(reply.text)
        failure = None
        if not reply.text.strip() and not allow_empty:
            failure = f"{self.tool.name} returned nothing from {self.slug}"
        elif schema is not None:
            try:
                found = _mismatch(json.loads(reply.text), schema)
            except ValueError:
                found = ""  # complete_json words this one
            if found:
                failure = f"{self.tool.name} broke the agreed shape: {found}"
        console.end(call, reply=reply.text, error=failure or "", prompt_tokens=reply.prompt_tokens, output_tokens=reply.output_tokens)
        if failure:
            raise LLMError(failure)
        return reply.text

    def _run(self, prompt: str, schema: dict | None, images: list[str], call: int) -> Reply:
        with tempfile.TemporaryDirectory(prefix="amelia-cli-") as files:
            folder = os.path.join(files, "work")  # what the tool sees as its project: nothing, not even the schema or the images
            os.mkdir(folder)
            argv, stdin = self.tool.build(self.slug, prompt, schema, images, files)
            argv = [_found(argv[0]), *argv[1:]]
            try:
                process = subprocess.Popen(argv, cwd=folder, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                           text=True, encoding="utf-8", errors="replace", start_new_session=True)
            except OSError as exc:
                raise LLMError(f"{self.tool.name} could not start: {exc}") from exc
            return self._follow(process, stdin, call)

    def _follow(self, process: subprocess.Popen, stdin: str, call: int) -> Reply:
        lines: queue.Queue = queue.Queue()
        said: list[str] = []
        threading.Thread(target=_feed, args=(process, stdin), daemon=True).start()
        threading.Thread(target=_pour, args=(process.stdout, lines), daemon=True).start()
        threading.Thread(target=_keep, args=(process.stderr, said), daemon=True).start()
        deadline = time.monotonic() + self.timeout
        reply = Reply()
        try:
            while True:
                runs.check()  # a stop reaches a tool that is quiet too, not only between pieces
                if time.monotonic() > deadline:
                    raise LLMError(f"{self.tool.name} timed out after {self.timeout:.0f} s")
                try:
                    line = lines.get(timeout=0.2)
                except queue.Empty:
                    continue
                if line is None:
                    break
                try:
                    event = json.loads(line)
                except ValueError:
                    continue  # a tool's own notice, not part of the reply
                if not isinstance(event, dict):
                    continue
                self.tool.read(event, reply)
                for piece in reply.written:
                    if piece:
                        console.progress(call, piece)
                reply.written.clear()
                if reply.tool_use:
                    raise LLMError(f"{self.tool.name} tried to use {reply.tool_use} on its own, so this call was stopped. "
                                   "The text it was reading may be telling it to.")
            code = process.wait(timeout=30)
        except subprocess.TimeoutExpired as exc:
            raise LLMError(f"{self.tool.name} did not finish") from exc
        finally:
            _end(process)
        if reply.error:
            raise LLMError(f"{self.tool.name}: {reply.error}")
        if code != 0 or not reply.finished:
            raise LLMError(f"{self.tool.name} stopped without an answer: {''.join(said)[-300:].strip() or f'exit {code}'}")
        return reply


def _feed(process: subprocess.Popen, stdin: str) -> None:
    try:
        process.stdin.write(stdin)
        process.stdin.close()
    except (OSError, ValueError):
        pass  # it ended or was stopped before reading everything; its exit says what happened


def _pour(stream, lines: queue.Queue) -> None:
    try:
        for line in stream:
            lines.put(line)
    except ValueError:
        pass
    lines.put(None)


def _keep(stream, said: list[str]) -> None:
    try:
        for line in stream:
            said.append(line)
            del said[:-20]
    except ValueError:
        pass


def _end(process: subprocess.Popen) -> None:
    """These tools start children of their own, so the whole group goes."""
    if process.poll() is None:
        try:
            os.killpg(process.pid, 9)
        except (ProcessLookupError, PermissionError):
            pass
        process.wait()


# --- What can be chosen ---

_kept: dict = {"at": 0.0, "found": None}
_kept_lock = threading.Lock()


def _list_one(tool: Tool) -> tuple[list[dict], str]:
    if not shutil.which(tool.command, path=os.pathsep.join([os.environ.get("PATH", ""), *EXTRA_PATH])):
        return [], ""  # not installed is not a problem: nothing to choose, nothing to say
    try:
        listed, problem = tool.models()
    except (OSError, subprocess.SubprocessError) as exc:
        return [], f"{tool.name} did not answer: {exc}"
    notice = f"Sends your files' text to {tool.company} and uses your {tool.plan} plan."
    return [{"name": f"{tool.prefix}:{m['slug']}", "label": m["label"], "group": tool.name, "vision": tool.sees, "online": True, "notice": notice}
            for m in listed], problem


def available_models() -> tuple[list[dict], list[str]]:
    """Every model the signed-in tools offer, and what stands in the way of the others. Kept a little: listing takes seconds."""
    with _kept_lock:
        if _kept["found"] is not None and time.monotonic() - _kept["at"] < LIST_KEPT_SECONDS:
            return _kept["found"]
        with ThreadPoolExecutor(len(TOOLS)) as pool:
            results = list(pool.map(_list_one, TOOLS))
        found = ([m for listed, _ in results for m in listed], [problem for _, problem in results if problem])
        _kept.update(at=time.monotonic(), found=found)
        return found


def forget_models() -> None:
    with _kept_lock:
        _kept.update(at=0.0, found=None)
