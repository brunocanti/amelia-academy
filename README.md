# Amelia Academy

Amelia Academy turns documents, such as scientific papers, into question-and-answer datasets that a person reviews, then fine-tunes a local model on them and shows how the model changed.

You upload a file. A local model reads it passage by passage and drafts pairs: things the document says, questions built on a false premise, and questions the document does not answer. You keep or drop each pair. You export the approved pairs as JSONL and train a LoRA adapter with MLX. Then you compare the base model and the trained one on what it studied and on new questions.

Everything runs on your machine. Models run through Ollama or MLX, or through the CLI of a tool you have already installed and signed in to (`claude`, `codex`). The app never calls a model API directly.

## The idea: the hard part stays underneath

Advanced technology should be easy to use. However much happens behind the screen, Amelia should feel simple:

- **A simple question gets a simple answer.** Each decision is a question anyone understands, with short answers: "Which one is right?", "This one", "Both are right".
- **No machine vocabulary.** You do not need to learn the system's terms to act.
- **Clicking is safe.** Every decision can be undone, and the undo shows up right away.
- **The model drafts, the person chooses.** Nothing changes without your choice.
- **An option exists only if you need it.** When in doubt, a good default and nothing to configure.

Easy does not mean hidden. Failures, limits and uncertainty stay visible, in plain words.

## Status

Research prototype. Single user, local, no accounts. It works end to end on macOS with Apple Silicon. The design documents (`docs/`) are in Portuguese, and some of them describe a longer-term target (Rust, PostgreSQL) that is not built yet. Start with `docs/architecture/estado-atual.md` for what exists today.

## Requirements

- Python 3.12 or newer, Node 20 or newer
- [Ollama](https://ollama.com) with a model that supports structured output (default `qwen3:14b`)
- For training: macOS on Apple Silicon (MLX). Reading, review and export work on any OS.

## Install and run

```bash
ollama pull qwen3:14b
```

```bash
cd app/backend && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn amelia_academy.api:app --port 8000
```

```bash
cd app/ui && npm ci && npm run dev
```

Open http://localhost:5173. The UI proxies `/api` to port 8000. Data is stored in `app/var/` (SQLite and uploaded files), which is not tracked.

Training uses a separate environment:

```bash
cd app/trainer && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
```

More detail, including the rules the app enforces and the model settings, is in [`app/README.md`](app/README.md).

## Try it

Any PDF works. For a shareable demo, use open-access papers under CC BY, for example from [PLOS](https://journals.plos.org). See [`examples/README.md`](examples/README.md).

## Tests

```bash
cd app/backend && PYTHONPATH=. .venv/bin/pytest -q
```

Tests that need a live model are reported as `skipped`, with the reason, when Ollama is not running.

## Layout

```
app/backend    FastAPI service: reading, pairs, curation, export, training runs
app/trainer    isolated MLX worker for LoRA training
app/ui         React (Vite) interface
contracts      JSON Schemas and fixtures for datasets and manifests
docs           architecture, decisions (adr/), specs (Portuguese)
fixtures       seed projects used by tests
research_notes background research
```

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

MIT, see [LICENSE](LICENSE). Models you download (Gemma, Qwen and others) keep their own licenses. Papers you process keep theirs: check them before you share a dataset.

## Acknowledgements

Parts of this project were written with the help of AI coding assistants (Claude and Codex).
