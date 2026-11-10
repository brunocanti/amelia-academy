# ADR 015: Three kinds of pair at reading, labeled in every export

- **Status:** Accepted, built
- **Date:** 2026-11-06
- **Amends:** ADR 013, ADR 014 (items 3 and 5)
- **Scope:** Reading a file, curation and export. Details in spec 012

## Context

A dataset of answered questions teaches a model to answer everything and to accept what it is told. Files should also produce questions they do not answer and questions built on a false claim. Both also say something to any agent reading the knowledge, not only to a fine-tune.

## Decision

1. **Reading a file can write three kinds of pair:** answered, unanswered and false premise, by a share the person sets at reading (0 to 30% each, starting at 10%). All are born `proposed`.
2. **The third kind carries the error in the question, not in the answer.** A wrong answer in `train.jsonl` would be taught as right, and `mlx_lm.lora` documents no negative examples. Preference training (DPO) stays possible later.
3. **Each false premise comes with its true version,** inside the same share, so a model does not learn to deny every confirmation. True versions go to training only.
4. **False premises and unanswered questions are knowledge when labeled.** They go to `memory.jsonl` with a `kind`, and to the wiki in their own sections, never as ordinary content.
5. **Labels say only what is known.** A false premise is a "possible mistake": the model wrote it, nobody observed it. An unanswered question means the files checked do not answer it, and returns to review when a new file seems to.

## Consequences

- No code proves a premise false or a question unanswered. The checks only discard; the person decides.
- A false claim is now present in memory and wiki, so a consumer that ignores `kind` can repeat it.
- Unanswered questions mark a gap inside the subject, not its border. Questions outside the subject are not written.
- The shares are a starting guess. Too many refusals or denials only show when a model is tested, and Evaluate does not exist.
