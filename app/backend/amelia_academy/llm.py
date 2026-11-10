"""The model client: what every model can do, and Ollama. Tools reached by command line are in `cli_tools`. No silent model fallback.

Anything the platform reads as data (themes, samples) goes through `complete_json`:
the schema is enforced by Ollama's structured output, and a reply that still does not
parse or does not match the schema fails visibly. The one repair is `_keep_formulas`: it
only gives a formula back its backslash, and never touches anything else in the reply.
"""

import base64
import json
import re
import time

import httpx

from . import agents, console, runs

FIGURE_SCHEMA = {
    "type": "object",
    "properties": {"visible_text": {"type": "string"}, "reading": {"type": "string"}},
    "required": ["visible_text", "reading"],
}

# A figure with many similar labels can send the model repeating one line until the timeout: tens of
# thousands of tokens, 10 minutes. The longest good reading measured is about 1,050 tokens.
FIGURE_MAX_TOKENS = 3000
FIGURE_RETRY_REPEAT_PENALTY = 1.3  # only on the retry: from the start it thins transcriptions of charts

# Any structured reply. A model that starts repeating itself otherwise writes until the 10-minute timeout: a reading
# of 34 passages ran to 48,000 tokens. The longest good reading of a window is far below this.
MAX_TOKENS = 4000


# Last attempt on a figure that keeps repeating: the transcription is where it loops, so ask only for the reading.
FIGURE_READING_ONLY_SCHEMA = {
    "type": "object",
    "properties": {"reading": {"type": "string"}},
    "required": ["reading"],
}


class LLMError(RuntimeError):
    pass


def plain_error(exc: Exception) -> str:
    """What the model's server said, without the HTTP wrapping, for a person to read."""
    said = re.search(r'"error":\s*"([^"]+)"', str(exc))
    return said.group(1) if said else str(exc)


class OutputCapped(LLMError):
    """The model reached the output cap, so what it wrote is cut off."""


def installed_models(base_url: str = "http://localhost:11434") -> list[dict]:
    """Models Ollama has pulled. The UI lists these; nothing is invented if the call fails."""
    url = base_url.rstrip("/")
    try:
        response = httpx.get(f"{url}/api/tags", timeout=5)
    except httpx.HTTPError as exc:
        raise LLMError(f"ollama unreachable at {url}: {exc}") from exc
    if response.status_code != 200:
        raise LLMError(f"ollama returned {response.status_code}: {response.text[:300]}")
    models = response.json().get("models") or []
    return [
        {"name": m["name"], "size": m.get("size") or 0, "vision": "vision" in (m.get("capabilities") or [])}
        for m in models if m.get("name")
    ]


# A model writing LaTeX in JSON often leaves one backslash, and that is still valid JSON: \tilde reads as a tab and "ilde".
# \b, \f and \r before a letter are never real. \t and \n are common, so only the rest of a known formula name counts, and
# never one that is also a word ("\to", "\tan", "\ne", "\ni", "\no" stay as a tab or a line break followed by that word).
_ONE_BACKSLASH = re.compile(
    r"\\(?:\\"  # already doubled: step over it
    r"|(?P<formula>[bfr](?=[A-Za-z])"
    r"|t(?=(?:ilde|heta|au|imes|anh|frac|riangle|extbf|extit|extrm|exttt)(?![A-Za-z])|ext\{)"
    r"|n(?=(?:u|eq|abla|eg|otin|ot|onumber|mid|geq|leq)(?![A-Za-z]))))"
)


def _keep_formulas(raw: str) -> str:
    return _ONE_BACKSLASH.sub(lambda m: "\\" + m.group(0) if m.group("formula") else m.group(0), raw)


class ModelClient:
    """What the platform asks of a model. A kind of client only says how one call reaches it, in `_chat`."""
    model: str

    @property
    def shown(self) -> str:
        """The model as a person reads it, in what a failure says."""
        return self.model

    def _chat(self, prompt: str, temperature: float, schema: dict | None = None,
              images: list[str] | None = None, allow_empty: bool = False, options: dict | None = None) -> str:
        raise NotImplementedError

    def complete(self, prompt: str, temperature: float = 0.9) -> str:
        return self._chat(prompt, temperature)

    def read_image(self, png: bytes) -> str:
        """Transcribe the text in an image. The result is a model proposal, never the original text."""
        encoded = base64.b64encode(png).decode("ascii")
        with console.acting("figure_reader"):
            text = self._chat(agents.prompt("figure_reader", "image_text"), 0.0, images=[encoded], allow_empty=True).strip()
        return "" if text == "NO_TEXT" else text

    def read_figure(self, png: bytes) -> dict:
        """Read visible text and say what the figure shows. The reading is the model's, not a quotation."""
        encoded = base64.b64encode(png).decode("ascii")
        attempts = (
            ("figure", FIGURE_SCHEMA, {}),
            ("figure", FIGURE_SCHEMA, {"repeat_penalty": FIGURE_RETRY_REPEAT_PENALTY}),
            ("reading_only", FIGURE_READING_ONLY_SCHEMA, {}),
        )
        for prompt, schema, options in attempts:
            try:
                with console.acting("figure_reader"):
                    data = self.complete_json(agents.prompt("figure_reader", prompt), schema, temperature=0.1, images=[encoded],
                                              options={"num_predict": FIGURE_MAX_TOKENS, **options})
                break
            except OutputCapped:
                continue
        else:
            raise LLMError(f"model {self.shown} kept repeating itself on this figure, "
                           f"{len(attempts)} times: stopped at {FIGURE_MAX_TOKENS} tokens")
        visible = str(data.get("visible_text") or "").strip()
        if visible == "NO_TEXT":
            visible = ""
        return {"visible_text": visible, "reading": str(data.get("reading") or "").strip()}

    def complete_json(self, prompt: str, schema: dict, temperature: float = 0.9, images: list[str] | None = None,
                      options: dict | None = None) -> dict:
        content = self._chat(prompt, temperature, schema, images=images, options={"num_predict": MAX_TOKENS, **(options or {})})
        try:
            data = json.loads(_keep_formulas(content))
        except json.JSONDecodeError as exc:
            console.problem(f"reply is not the agreed shape: {exc}")
            raise LLMError(f"model {self.shown} broke the structured-output contract: {exc}") from exc
        if not isinstance(data, dict):
            console.problem(f"reply is {type(data).__name__}, not an object")
            raise LLMError(f"model {self.shown} returned {type(data).__name__}, expected an object")
        return data

    def complete_json_batch(self, prompt: str, schema: dict, temperature: float = 0.0) -> dict:
        """One structured model call for a batch of independent judgments."""
        content = self._chat(prompt, temperature, schema=schema, options={"num_predict": MAX_TOKENS})
        try:
            data = json.loads(_keep_formulas(content))
        except json.JSONDecodeError as exc:
            raise LLMError(f"model {self.shown} broke the batch-output contract: {exc}") from exc
        if not isinstance(data, dict):
            raise LLMError(f"model {self.shown} returned {type(data).__name__}, expected a batch object")
        return data


class OllamaClient(ModelClient):
    def __init__(self, model: str, base_url: str = "http://localhost:11434", timeout: float = 600.0):
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def _chat(self, prompt: str, temperature: float, schema: dict | None = None,
              images: list[str] | None = None, allow_empty: bool = False, options: dict | None = None) -> str:
        message = {"role": "user", "content": prompt}
        if images:
            message["images"] = images
        payload = {
            "model": self.model,
            "messages": [message],
            # Keep the selected model warm across consecutive file reads and Challenge batches.
            "keep_alive": "10m",
            "stream": True,  # so the console shows the reply as it is written
            "think": False,  # measured on a real window: thinking used the whole 4,000-token cap and left no answer
            "options": {"temperature": temperature, **(options or {})},
        }
        if schema is not None:
            payload["format"] = schema
        runs.check()
        call = console.begin(self.model, prompt)
        try:
            from . import gpu
            with gpu.generation():
                body = self._post(payload, call)
        except LLMError as exc:
            console.end(call, error=str(exc))
            raise
        except runs.Stopped:
            console.end(call, stopped=True)
            raise
        content = (body.get("message") or {}).get("content", "")
        failure = None
        if options and "num_predict" in options and body.get("done_reason") == "length":
            failure = OutputCapped(f"model {self.model} reached the {options['num_predict']}-token cap")
        elif not content.strip() and not allow_empty:
            failure = LLMError(f"ollama model {self.model} returned empty content")
        console.end(call, reply=content, error=str(failure or ""),
                    prompt_tokens=body.get("prompt_eval_count") or 0, output_tokens=body.get("eval_count") or 0)
        if failure:
            raise failure
        return content

    def _post(self, payload: dict, call: int) -> dict:
        """Reads the reply as it arrives. A stream resets httpx's timeout at each piece, so the total limit is kept here."""
        deadline = time.monotonic() + self.timeout
        written, last = [], {}
        try:
            with httpx.stream("POST", f"{self.base_url}/api/chat", json=payload, timeout=self.timeout) as r:
                if r.status_code != 200:
                    r.read()
                    raise LLMError(f"ollama returned {r.status_code}: {r.text[:300]}")
                for raw in r.iter_lines():
                    if not raw.strip():
                        continue
                    runs.check()  # leaving this block closes the stream, and Ollama drops the call
                    last = json.loads(raw)
                    if last.get("error"):
                        raise LLMError(f"ollama reported an error: {last['error']}")
                    piece = (last.get("message") or {}).get("content", "")
                    if piece:
                        written.append(piece)
                        console.progress(call, piece)
                    if time.monotonic() > deadline:
                        raise LLMError(f"ollama unreachable at {self.base_url}: timed out after {self.timeout:.0f} s")
        except httpx.HTTPError as exc:
            raise LLMError(f"ollama unreachable at {self.base_url}: {exc}") from exc
        except ValueError as exc:
            raise LLMError(f"ollama sent a reply that could not be read: {exc}") from exc
        return {**last, "message": {"content": "".join(written)}}
