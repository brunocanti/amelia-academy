# ADR 011: Natural, review-first project workflow

- **Status:** Accepted
- **Date:** 2026-11-03
- **Scope:** Amelia Academy project workspace UI

## Context

Amelia Academy is a general platform. Amelia and a document project such as Comprimildo are two projects on the same workflow. A fixed menu of generic tabs makes it hard to see what depends on what. Splitting the menu into a behavior track and a knowledge track made the card look like a separate product.

The interface should make the workflow and its prerequisites legible without asking the operator to understand internal agents, model orchestration, deterministic/non-deterministic boundaries, or implementation jargon.

## Decision

1. The default product interface is English. Project content language remains an independent project setting.
2. The main navigation is a project workflow, not a set of unrelated feature silos. Its stage state is computed from saved backend data and includes **done**, **active**, **ready**, **locked**, and **planned**.
3. The overview presents one next recommended action and a connected map of stages. A locked stage identifies its prerequisite and offers a route to that prerequisite. An unavailable stage is labeled honestly; it never displays mock results as real work.
4. Creating a project does not ask for an objective. The menu is Sources, Knowledge, Samples, Dataset, then Train, Evaluate and Publish. Knowledge is one graph: a node is knowledge (cited claims) or behavior (the card). Samples are written from a node selected as a theme. Train, Evaluate and Publish stay visible and say they are not built.
5. The UI prioritizes review decisions—accept, edit, reject, approve—over manual configuration. Detail that is not needed for the immediate decision is disclosed progressively; short tooltips explain terms and dependencies when useful.
6. Copy is operational and concise. Do not add promotional slogans or decorative narration to workflow screens. Show counts, state, source/provenance, dependency, next action, or a concrete limitation.
7. Offer System, Light, and Dark appearance modes. Theme colors are tokens so both modes remain legible and consistent with Amelia 3 visual-system colors.

## Consequences

- Workflow state has one source of truth in the project pipeline API; the interface does not invent progress from navigation clicks.
- Stage navigation is the same for every project. The sample writer follows the node type. A knowledge node does not use the conversational card prompt.
- Future multi-agent coordination can remain behind the same review-oriented UI; orchestration details are not required on the main path.
- User-facing examples or fixture content must be labeled and must never be presented as saved model output.

## Implementation notes

The React workspace reads `/projects/{id}/pipeline`, shows dependency-aware stage states and a next action, and has a system/light/dark selector. One model choice sits in the top bar and is the same control used for extraction, sample writing and card suggestions. The running menu and the graph are described in `docs/architecture/estado-atual.md`. `docs/brand/visual-system.md` remains the source for the inherited visual language.
