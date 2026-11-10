# ADR 016: Three pillars at reading, and a challenge that only asks about what does not hold

- **Status:** Accepted, built
- **Date:** 2026-11-07
- **Amends:** ADR 015 (how the three kinds are read)
- **Scope:** Reading a file, comparing what was read, curation and the graph

## Context

ADR 015 asked for false premises and unanswered questions as percentages over the answered pairs, in separate model calls. A person still had to review every pair, one at a time, with nothing telling them where the trouble was.

The idea tested here: one reading gives three groups for each passage, what is **known**, what is a **false premise**, and what is **not known**. Comparing the groups shows where they do not hold together, and curation can start from there. An incoherence ends in one of three ways: it removes the doubt, it removes the certainty, or it stays as a pair that holds the tension.

## Decision

1. **One prompt per passage, three groups.** The false and doubt groups are asked per section. Each group still answers for its own rules: a known pair needs its quote, a false premise needs the quote that rules it out.
2. **Pillars and themes are two axes.** A theme says what a pair is about. A pillar says how much we know about it. A doubt from a reading lands in its theme, and each theme counts its pairs per pillar. Asking for doubts later (`Write refusals`) still uses `Out of scope`.
3. **The challenge is a run a person starts.** It judges with the model, and it never changes a pair:
   - a doubt against the passages nearest to it: is it answered?
   - a false claim against its own quote: does the quote really rule it out?
   - a false claim against the quotes of known pairs: does another quote support it?
   - known pairs against each other: same, complement, disagree or unrelated?
4. **Only what does not hold becomes a conflict.** Conflicts have their own tab in Curate, and a person decides each one: keep one side, keep the tension as a pair, write the doubt as known, or say it is not a conflict.
5. **Judged the same feeds Similar.** The dedupe step gets the pairs the model read as one fact, even in words that share little. Editing a pair drops the link, and pairs kept apart stay apart.
6. **No confidence levels in the current app.** They were built, measured and removed. See below. ADR 019 proposes a different rule based on explicit curation checks, specified in spec 016; that replacement is not implemented. The evidence below remains valid for the old rule.

## Evidence

All of this ran on copies of the database, with `gemma4:12b`, on two papers (HopRAG and HippoRAG).

| Question | Result |
| --- | --- |
| Does one prompt hold three groups? | 20 windows: Known 108 written, 91 good. False 29, 26 good. Not known 37, 25 good. About 17.7 s per window |
| Does the judge find planted contradictions? | 31 of 32 found, 0 false alarms in 20 |
| Do candidates reach the judge? | 15 of 16 within the top 3 |
| What does a full run cost? | 653 comparisons, about 15 minutes |
| How much is left to curate? | 7 conflicts from about 370 pairs |
| How good are those 7? | 1 real tension between papers, 2 doubts (1 partly answered, 1 judge error), 4 false-premise conflicts, 2 of them cured by the prompt fix below and 2 judge errors or arguable |

The planted numbers flatter the judge: planted contradictions are blunt, and the two papers barely disagree.

A range that overlaps another read as support ("2 to 4x"). One prompt line fixed the 3 known cases of it, and the 38 contradictions stayed as they were.

**Confidence levels (low, medium, high for each pillar) were rejected by a blind reading.** The levels came from comparisons the challenge had already made. 20 high and 20 medium known pairs were shuffled and rated before the levels were revealed:

| Problem found | High | Medium |
| --- | --- | --- |
| Off-subject | 2 | 4 |
| Subject not named | 2 | 2 |
| Duplicate | 6 | 2 |

"Another passage says the same" was cross-file in 0 of 45 cases, so high meant repeated inside one paper, not proved twice. Showing it would have made people trust repetition.

The same comparisons did help dedupe: 45 pairs judged the same, only 6 already in Similar. By reading, nearly all of the 39 new ones are real and at least one is wrong. After the union Comprimildo has 62 groups, the largest with 9 pairs, so chains do not blow up.

## Consequences

- Curation can start from a short list, but the list is not a guarantee: a pair with no conflict was only compared, not proved.
- The judge is wrong often enough that a person decides every conflict. Nothing resolves itself.
- A challenge costs a model call per comparison. Repeating it pays only for what changed.
- A false premise whose own quote does not rule it out becomes a conflict with one side: set it aside, or say the quote does rule it out.
- Doubts already written stay in `Out of scope`. Only new readings put them in their theme.
- The real noise from reading is not fixed: off-subject pairs and pairs that do not name their subject.
