You write question-and-answer pairs for a training dataset called "$project". They teach a model not to accept a mistake from the person asking.

Below are established facts, each with the quote that proves it. For each fact, return one item. The quote must directly prove the false claim wrong by stating the opposite result, relation, or number. A merely related quote is not enough; skip the fact if the quote does not establish the correction. Vary question forms. Avoid repeating one template, especially "Why is ... always ...?":
- "fact": its label, such as "P1".
- "false_claim": one sentence in $language that the quote contradicts and that a reader could plausibly believe. Change exactly one verifiable detail by swapping a number or date (only when the fact has one), swapping an entity, or inverting a relation. It must be false according to the quote; something the quote merely leaves out is not a false claim.
- "question": a question in $language in the form listed with the fact, making sense alone and naming its subject. $states_the_claim
- "answer": at most $max_sentences sentences in $language that say plainly what is wrong and give what is right, using only the quote. Keep numbers exactly as written. Never say you do not know. Never mention a quote, text, document, file or source.
- "true_question": the same question in $language with the false claim replaced by what the quote says, stated and asking for confirmation.
- "true_answer": at most $max_sentences sentences in $language confirming it, using only the quote.

Skip a fact rather than force a mistake that nobody would make.

Facts:
$facts
