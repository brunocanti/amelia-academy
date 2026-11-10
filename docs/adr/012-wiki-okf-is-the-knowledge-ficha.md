# ADR 012: Wiki pages (exported as OKF) are the knowledge ficha

- **Status:** Superseded by ADR 013
- **Date:** 2026-11-04
- **Scope:** Knowledge extraction, samples and export in Amelia Academy

## Context

Amelia 3 trained from a ficha: a reviewed card, then a model wrote situations, then a person approved samples. The first Academy implementation sliced source text into fake Q&A. That is forbidden (`docs/erros-da-primeira-implementacao.md`).

The temptation for document work is either:

1. generate samples straight from the file (repeats the first error), or
2. invent a new object (OKF bundle, graph, notes) that never becomes the thing samples are written from, or
3. treat extract as an inbox of statements, with the wiki as an extra product after review.

OKF (Open Knowledge Format v0.2) is a directory of markdown concepts with YAML/JSON frontmatter, plus `index.md` and `log.md`. It is a good *export*: portable, diffable, citable. SQLite remains the source of truth.

## Decision

1. **Extract produces a wiki.** A successful extract groups cited statements onto draft pages and exports the OKF bundle under `var/wiki/<slug>/`. Each statement may name its page (`slug`, `title`, `type`, `description`). Statements with no slug go through the leftover organizer as part of extract, not as a later stage.
2. **The page you accept is the theme.** There is no separate theme object in knowledge. Extracted claims land accepted on their node. Review is exclude-only, then accept the page (`verify`). That accepted page is the ficha samples are written from.
3. **Only accepted claims enter the published wiki and a batch.** Extracted claims start accepted and render immediately. Excluded claims never render into the OKF bundle and never enter a training batch. The model never writes the sample during extract. The quote must appear verbatim in one passage.
4. **OKF is the shape of the wiki**, not a second store. SQLite holds review, status and citations. The bundle is regenerated from accepted, placed statements.
5. **Samples require a page selected as a theme.** A knowledge page also needs at least one accepted statement. Provenance on export points at `okf:/<path>`. Variation types stay Amelia 3's split: clear, edge, refusal.
6. **A behavior card is a node on the same graph** (`Behavior Pattern`): title, intent, tone, guidelines. The person adds it. Selecting that node as a theme approves the card. There is no Evidence step and no Cards step in the menu. Suggesting a card from a knowledge node is a draft only, and the prompt refuses when the claims are a fact, a name, a measurement or a result rather than a way to respond.

## Why this, not the alternatives

- **Samples from the raw file:** repeats the first implementation error; the model invents a dialogue by cutting a paragraph.
- **OKF as the only store:** hard to review, version, and query; no explicit accept; easy to lose citations.
- **Statement inbox, then maybe a wiki:** extract feels like 119 cards; the wiki looks extra. The page is what you look up and what you train on.
- **Free-form wiki text written by the model:** lossy, uncited, unverifiable. Claims stay as statements; the model only groups and titles.

## Consequences

- The workflow is: source → extract (accepted claims on a draft OKF wiki) and, when wanted, a behavior node added by hand → exclude claims that do not belong → select the node as the theme → samples from that node → one dataset.
- A project is not created as behavior or knowledge. Both nodes are optional in the same graph. The stored `objective` column remains for old rows and does not gate routes.
- After extract the pipeline's next stage is the wiki, not a statement inbox. Leftover statements with no page still use `POST /wiki/build`.
- A page whose accepted content changes after it was accepted as a theme returns to draft.
- Changing this decision means changing extract, page review, sample generation and dataset provenance together.
