You write training conversations for an assistant that does a job for people. The output is synthetic dialogue, not a summary or a rewrite of this instruction.

Write exactly $count distinct situations. Each has ONE natural user message asking for something concrete, followed by ONE assistant reply of at most $max_sentences sentences that does what the card below says.

${identity_block}Approved card — follow its intent and constraints, but do not quote or paraphrase its text:
Intent: $intent
Tone: $tone
Guidelines: $guidelines
Description: $description
Requested variation: $variation — $variation_instruction

Quality requirements:
- Make all $count situations meaningfully different in context and wording; do not reuse one template with swapped nouns.
- Answer the request directly. No help-desk filler ("How can I help", "I'd be happy", "Como posso ajudar") and no instruction echo.
- Do not invent facts a real assistant could not know from the message. When something needed is missing, say what is missing.
- State only what is generally accepted about the subject. When the right answer depends on the situation, say on what. Do not treat two different terms as the same thing.
- Every situation must be one where the Description above applies; a situation about something else is not usable.
- Write $write_in.

Return the $count situations as a list; each has "user_message" and "response_text".
