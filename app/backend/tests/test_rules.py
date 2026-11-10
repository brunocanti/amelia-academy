from amelia_academy import rules


def test_valid_sample_passes():
    reasons = rules.check_sample(
        "I have been feeling stuck with my project since last week.",
        "That sounds heavy. Do you want to tell me what part feels stuck?",
    )
    assert reasons == []


def test_help_desk_filler_is_rejected():
    reasons = rules.check_sample("I feel lost.", "I'm here to listen without judgment. How can I help?")
    assert any("forbidden fragment" in r for r in reasons)


def test_instruction_echo_is_rejected():
    reasons = rules.check_sample("The assistant stays forever with me.", "Okay.")
    assert any("forbidden fragment" in r for r in reasons)


def test_too_many_sentences_is_rejected():
    reasons = rules.check_sample("I am tired.", "One. Two. Three. Four.")
    assert "response_text has more than two sentences" in reasons


def test_user_line_copied_from_pattern_is_rejected():
    pattern = "Genuine contentment, presence, and bond without possession."
    reasons = rules.check_sample("Genuine contentment, presence, and bond without possession.", "Fine.", pattern)
    assert "user_message copied from pattern text" in reasons


def test_empty_lines_are_rejected():
    assert rules.check_sample("", "x") == ["empty user_message"]


def test_hash_is_stable_under_whitespace_and_case():
    a = rules.content_hash("Hello  there", "Reply")
    b = rules.content_hash("hello there", "reply")
    assert a == b


def test_portuguese_filler_is_rejected():
    reasons = rules.check_sample("Estou um pouco cansado.", "Estou aqui para ajudar, como posso ajudar?")
    assert any("forbidden fragment" in r for r in reasons)


def test_generic_portuguese_follow_up_is_rejected():
    reasons = rules.check_sample("Hoje foi um dia difícil.", "O que te faz sentir assim hoje?")
    assert any("forbidden fragment" in r for r in reasons)
