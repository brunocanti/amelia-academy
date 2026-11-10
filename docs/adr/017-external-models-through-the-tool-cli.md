# ADR 017: External models always run through the tool's command line

- **Status:** Accepted, built
- **Date:** 2026-11-07
- **Scope:** Choosing a model, every model call, the model list

## Context

The platform only reached models through Ollama. People already have Claude, Codex and Antigravity installed and signed in, and want to choose among them and their models. A provider's API would need keys and separate billing; these tools run on the plan the person already has.

The cost is that these tools are agents. They can read files and run commands, and a file's text is untrusted.

## Decision

1. **Command line only, never a provider's API.** `cli_tools.py` has one way to call and read each tool. There is no provider SDK and no API key.
2. **The name says who runs it.** `claude-cli:`, `codex-cli:` and `agy-cli:` are exact prefixes, because Ollama names have `:` too. A name without a prefix is an Ollama model, so what is saved keeps working and resuming a run finds its tool. The person never sees the prefix.
3. **The local model stays the default.** Sending text out is a choice the person makes. While an online model is chosen, a line says who receives the text and whose plan it uses.
4. **A call has nothing to reach.** Each call runs in an empty temporary folder, deleted afterwards, with every tool off where the command allows it. Where it does not (Codex, Antigravity), the tool is held to read-only or sandboxed, and the call is stopped the moment the model reaches for a tool.
5. **The reply is checked here.** Each reply is validated against the schema locally, whatever the tool claims.
6. **Antigravity is asked for the shape in words.** Its `--json-schema` flag filled the fields without the model understanding them: `question` came back holding the prompt and `answer` holding the whole reply, which passes every shape check. The flag is not used, and what it fills in is ignored.
7. **A tool that is missing is not a problem.** Not installed: nothing to choose, nothing to say. Installed and not signed in: the person is told what to run.

## Consequences

- What a tool cannot honour is dropped: temperature, repeat penalty and the output cap have no flag. A runaway reply ends at the 600 s limit, not at a token count.
- Every call carries the tool's own overhead. Measured on a 600-character file: about 1.5K input tokens on Claude, 13-14K on Codex, 8-9K on Antigravity. On a file of 416 passages that is about 6M input tokens on Codex.
- Codex and Antigravity can still read outside the empty folder until the call is stopped. Antigravity has about 60 tools and no flag to turn them off.
- Antigravity's schema is a request in words, so only the local check holds it. A correct shape with wrong content is not detected there, as on every model; curation decides.
- Antigravity has no known way to receive an image, so its models are listed as not seeing images.
- Using `agy` as a wrapper on a consumer plan appears in forums as possibly unsupported, with no official answer.
- A tool's new version can change its flags or events. The tests cover our reading of what the tools say, using stand-in scripts, not the tools themselves.
