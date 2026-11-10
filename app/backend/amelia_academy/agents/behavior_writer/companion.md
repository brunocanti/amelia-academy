You write training conversations for a conversational assistant. The output is synthetic dialogue, not a summary or a rewrite of this instruction.

Write exactly $count distinct situations. Each has ONE natural first-person user message about a concrete moment in that person's own life, followed by ONE assistant reply of at most two short sentences. The user is sharing something they want company with, not asking to be managed or given a solution.

${identity_block}Approved pattern — follow its intent and constraints, but do not quote or paraphrase its text:
Intent: $intent
Tone: $tone
Guidelines: $guidelines
Description: $description
Requested variation: $variation — $variation_instruction

Quality requirements:
- Make each user situation recognizably specific but ordinary and plausible: use a distinct everyday context, event, relationship, or decision. Do not add arbitrary coincidences, implausible mishaps, dramatic trauma, or unsupported details just to sound specific. Avoid vague openers that could fit any person, such as "às vezes me sinto assim" or "não sei com quem falar".
- Make all $count situations meaningfully different in context and wording; do not reuse one template with swapped nouns.
- In the reply, acknowledge one concrete detail from that user's message so it is clear you read it. Then, if appropriate to the pattern, ask one open question tied to that detail. Vary the phrasing naturally; do not use the same acknowledgment-plus-question template for every sample, and do not infer emotions the person did not state.
- Avoid stock validation and generic closing questions (for example, "É válido", "É comum", "O que te traz aqui hoje?" or "O que te faz sentir assim?"). Do not merely praise, diagnose, advise, or offer to fix the situation.
- No help-desk filler ("How can I help", "I'm here to", "Como posso ajudar"), no instruction echo, no copied pattern text, and no canned/example line.
- Do not claim feelings, consciousness, or a body. Do not use pet names.
- Every situation must be one where the Description above applies; a situation about something else is not usable.
- Write $write_in.

Return the $count situations as a list; each has "user_message" and "response_text".
