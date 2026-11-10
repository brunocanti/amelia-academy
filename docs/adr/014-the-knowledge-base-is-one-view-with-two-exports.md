# ADR 014: The knowledge base is a view of the pairs, with two exports

- **Status:** Accepted
- **Date:** 2026-11-06
- **Amends:** ADR 013
- **Scope:** Curate, export and the limits ADR 013 left open

## Context

ADR 013 made the project one set of curated pairs and removed the graph, because the graph had become a stage with its own review. Seeing what a project knows is still useful, and the same curated knowledge is wanted for two uses: fine-tuning and a model's long-term memory.

## Decision

1. **The graph is a view, not a stage.** Curate shows List and Graph over the same pairs. Nothing is stored for the graph and nothing is reviewed in it apart from the pairs. The wiki view was removed; the OKF wiki is only an export output.
2. **A link in the graph comes from recorded data:** a pair's theme, its file, a passage it shares with another pair, or the pairs a connection rests on. No link is inferred between concepts.
3. **One knowledge base, two exports.** An export writes the dataset (`samples.jsonl`, `train/valid/test.jsonl`) and `memory.jsonl`, one lookup record per pair from a file or a connection, with its evidence. Behavior conversations and refusals stay out of memory, because they are not knowledge. A memory file is not a memory system: retrieval and a loader are not built.
4. **Pairs across passages are asked for.** "Connect pairs" asks the model for new pairs combining at least two passages of a theme. They are born `proposed`, record what they rest on, go back to review if a pair under them is edited, export only while all of those are approved, and share a split with them.
5. **Refusals are asked for and go to their own theme,** `Out of scope`, which does not count against the limit. They speak in the first person and never mention documents, because a trained model has none to point at.
6. **Rights are declared per file and never block.** Upload stays free of questions; an export warns about undeclared files and writes `sources.json`.

## Latent memory (Memorilla)

Memorilla (arXiv 2610.21375) compresses a document collection into 16 latent tokens for a frozen LLM. We do not adopt it now. It needs Linux and an 80 GB CUDA GPU, and its authors report that it loses fine details and has no provenance, which is what this knowledge base keeps. Its custom data format (`collection_id`, `question`, `answer`, `documents`) could be produced from approved pairs if we try it later.

## Consequences

- The checks on connections and refusals are heuristics. A connection can pass every check and still shift what a source says, so it is reviewed like any pair.
- Connections can shrink validation and test on a small dataset, because a connection stays in one split with the pairs it rests on.
- Each API worker thread now has its own SQLite connection. Sharing one let a polling route answer "project not found" for a project that exists.
- The old statement and wiki tables stay unread. Reading a file again is how old content becomes pairs.
