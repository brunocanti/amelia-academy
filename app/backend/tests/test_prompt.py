from amelia_academy.workshop import build_prompt, VARIATION_INSTRUCTIONS
from amelia_academy import qa
from amelia_academy import qa


def test_generation_prompt_requests_grounded_and_varied_dialogue():
    pattern = {
        "intent": "A pessoa quer companhia sem depender da Amelia.",
        "tone": "calmo e direto",
        "guidelines": "Reconheça um detalhe e faça uma pergunta aberta.",
        "description": "Dificuldade leve, sem gerenciamento.",
    }
    prompt = build_prompt(pattern, "positive", 5)

    assert "exactly 5 distinct situations" in prompt
    assert "ordinary and plausible" in prompt
    assert "acknowledge one concrete detail" in prompt
    assert "do not use the same acknowledgment-plus-question template" in prompt
    assert "same language as the approved pattern" in prompt


def test_generation_prompt_names_the_project_language_and_keeps_to_the_card():
    pattern = {"intent": "i", "tone": "t", "guidelines": "g", "description": "When the user asks about PNG."}
    prompt = build_prompt(pattern, "positive", 2, "English")

    assert "in English, whatever language the examples above are in" in prompt
    assert "one where the Description above applies" in prompt


def test_should_not_apply_is_no_longer_written():
    assert "negative" not in VARIATION_INSTRUCTIONS


def test_identity_reaches_both_kinds_of_prompt_only_when_written():
    pattern = {"intent": "i", "tone": "t", "guidelines": "g", "description": "d"}
    for style in ("task", "companion"):
        with_story = build_prompt({**pattern, "style": style}, "positive", 2, "English", "My name is Lia. I was built in Recife.")
        assert "My name is Lia. I was built in Recife." in with_story
        assert "Do not add to it" in with_story
        assert "Who the assistant is" not in build_prompt({**pattern, "style": style}, "positive", 2, "English")


def test_project_scope_method_and_answer_style_change_reading_prompt_and_filter():
    project = {"display_name":"Yeast", "about_scope":"yeast stress response", "include_method":0, "answer_style":"short"}
    prompt = qa.pair_prompt(project, "English", [], [{"index":1,"text":"Yeast adapts to heat."}], 3)
    assert "yeast stress response" in prompt and "Do not write questions about protocols" in prompt
    assert qa.check_pair("Which protocol was used?", "A sample answer.", "Some protocol details.", project)
    assert not qa.check_pair("What happens to yeast?", "It adapts.", "Yeast adapts.", project)
    project.update(include_method=1, answer_style="explains")
    assert qa.answer_sentences(project) == 5


def test_method_details_no_blocks_procedures_materials_funding_and_encoder_details():
    project = {"display_name": "Yeast", "about_scope": "yeast stress response", "include_method": 0}
    prompt = qa.pair_prompt(project, "English", [], [{"index": 1, "text": "Yeast adapts."}], 3)
    assert "funding or funder roles" in prompt
    assert "Questions about findings and results remain welcome" in prompt

    blocked = [
        "How many layers does the encoder use?",
        "Did the funding sources have any role in the study design?",
        "Which plasmids were received as gifts from Takekazu Kunieda?",
        "What was the centrifugation speed and duration?",
        "What was the composition of the YPD media?",
        "How many hours were the samples incubated on the heat block?",
        "How much RNA was incubated with the 4 mM dNTP mix?",
        "How were the DNA sequences of the plasmids verified?",
    ]
    for question in blocked:
        assert any("method details" in reason for reason in qa.check_pair(question, "A concise answer.", "The source supports the answer.", project)), question

    assert any("method details" in reason for reason in qa.check_pair(
        "What did the encoder architecture use?", "It used 12 layers.", "The encoder used 12 layers.", project
    ))
    for question, answer in [
        ("How did the growth rate of yeast expressing the pRvLEAM plasmid compare to the control?", "It grew faster than the control."),
        ("What happened to CAHS3-GFP filaments when the hyperosmotic medium was replaced with isosmotic medium?", "The filaments disappeared."),
        ("What does the western blot analysis show regarding SAHS1-GFP?", "SAHS1-GFP stayed in the culture medium."),
    ]:
        assert not any("method details" in r for r in qa.check_pair(question, answer, answer, project)), question
    assert not qa.check_pair(
        "How did growth of yeast expressing HSP12 compare to control?",
        "Growth was higher than in the control.", "Yeast expressing HSP12 grew more than control cells.", project
    )


def test_method_filter_also_checks_the_answer():
    project = {"display_name": "Yeast", "include_method": 0}
    assert any("method details" in reason for reason in qa.check_pair(
        "How did yeast growth compare with control?", "Samples were incubated for 24 hours.",
        "Yeast growth was higher than control.", project
    ))


def test_project_scope_method_and_answer_style_change_reading_prompt_and_filter():
    project = {"display_name":"Yeast", "about_scope":"yeast stress response", "include_method":0, "answer_style":"short"}
    prompt = qa.pair_prompt(project, "English", [], [{"index":1,"text":"Yeast adapts to heat."}], 3)
    assert "yeast stress response" in prompt and "Do not write questions about protocols" in prompt
    assert qa.check_pair("Which protocol was used?", "A sample answer.", "Some protocol details.", project)
    assert not qa.check_pair("What happens to yeast?", "It adapts.", "Yeast adapts.", project)
    project.update(include_method=1, answer_style="explains")
    assert "at most 5 sentences" in qa.pair_prompt(project, "English", [], [{"index":1,"text":"Yeast adapts."}], 3)
