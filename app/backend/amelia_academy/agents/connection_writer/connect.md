You write question-and-answer pairs for a training dataset called "$project", theme "$theme".

Below are facts already established. Each comes from a different place in the material. Write up to $most new pairs that a person can only answer by putting at least two of these facts together: a comparison, a cause and its effect, a condition and what follows. Write fewer when the facts do not really connect. Return an empty list rather than force a link.

Each pair has:
- "question": a question in $language that makes sense alone, naming its subject.
- "answer": a direct answer in $language of at most $max_sentences sentences, using ONLY the facts. Keep numbers exactly as written. Do not mention "the facts" or any text.
- "facts": the labels of the facts the answer rests on, such as ["F1", "F4"]. At least two.

Do not restate one fact in other words.

Facts:
$facts
