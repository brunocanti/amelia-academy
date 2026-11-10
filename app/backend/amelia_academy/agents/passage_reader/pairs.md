You write question-and-answer pairs for a training dataset called "$project". A person who knows this subject should be able to learn from them.

From the section below, write up to $most pairs. Write fewer when the section holds less. Return an empty list when it holds nothing worth asking, such as a table of contents, bibliography, author names or acknowledgements. Never invent a pair to reach the number.

Each pair has:
- "question": a question in $language a person would really ask. It must make sense alone, naming its subject. Do not copy a sentence from the section as the question.
- "answer": a direct answer in $language of at most $max_sentences sentences, in your own words, using ONLY what the section says. Keep numbers and symbols exactly as written. Never mention "the text", "the section" or "the author" as the place the answer came from.
- "quote": copy the complete sentence that proves the answer, not a fragment. The neighbouring sentence before and after is available to resolve who or what a number describes; do not transfer a number to a different subject. Every sentence of the answer must be supported by the complete quoted sentence.
- "quote": the complete sentence that proves the answer, copied EXACTLY, character for character, from ONE passage, in its original language. The sentence before and after are supplied as context: use them to identify the subject of every number, but include their facts only when they are part of the same complete sentence. Do not translate, fix or paraphrase the quote.
- "theme": the slug of the theme the pair belongs to, from this closed list. Use "$other_theme" when no other theme fits; never force a pair into a theme that does not fit.
$themes

A passage marked "figure reading" describes a picture the reader will not see. Ask about the ideas it shows, naming them. Never mention a figure, diagram or image, a figure number, or a [P#] marker.

Section:
$passages
