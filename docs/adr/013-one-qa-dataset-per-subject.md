# ADR 013: One QA dataset per subject; the OKF wiki is an output

- **Status:** Accepted
- **Date:** 2026-11-05
- **Supersedes:** ADR 012
- **Amended by:** ADR 014 (the graph returns as a view; connections and refusals are available on request)
- **Scope:** Sources, samples, curation and export in Amelia Academy

## Context

ADR 012 made the wiki the object samples are written from: extract statements, group them on graph nodes, accept a page, select it as a theme, then write samples from it. Each step had its own review. To get a dataset from one file, a person walked through all of them.

What the person actually wants is simple: upload a file, get question and answer pairs from it, curate them, and end up with one dataset per subject, for fine-tuning or anything else.

## Decision

1. **A project is one dataset about one subject.** The flow is: create the project, upload a file, curate pairs by theme, export. Another file adds to the same dataset.
2. **The file produces pairs directly.** The model writes each pair from the text, citing a verbatim quote of the passage it came from. A pair whose quote is not in the passage is discarded and counted, visibly.
3. **Themes are a closed list with a limit.** `max_themes` is set when the project is created and can be changed later, never below the themes in use. The model must fit each pair into a listed theme, or into `Other`. A file may propose new themes only within the free slots, `ceil(free × 0.6)`, so a later file still has room. `Other` and behavior themes do not count.
4. **The person curates pairs, not statements.** A pair is born `proposed`. Editing its text returns it to `proposed`. Moving it to another theme keeps the decision. Only `approved` pairs are exported.
5. **The OKF wiki is generated at export,** one page per theme, from approved pairs only. It is an output, not an intermediate step, and nothing is written from it. SQLite stays the source of truth.
6. **Behaviors stay, because their pairs have no file to come from.** A card still has to be approved before conversations are written from it. The conversations land in the same curation list, under a theme for that card.

## Consequences

- The graph, the page review, the statement inbox and the source pipeline state are gone from the code and the interface.
- A pair is written from one passage window, so it rarely combines facts that are far apart in the file.
- Negative and refusal samples are not written for files. Only behavior cards produce them.
- Upload no longer asks for purpose or license basis; they default to `qa-dataset` and `unspecified`.
- The old tables stay in existing databases, unread. Behavior samples are adopted into the new table on migration. Statements and wiki pages are not converted.
