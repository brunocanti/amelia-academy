"""The agents directory: every agent has its card, every prompt loads, and a wrong name fails where it can be seen."""

import json

import pytest

from amelia_academy import agents
from amelia_academy.llm import _keep_formulas


def test_every_agent_has_a_card_and_the_console_order_holds():
    assert len(agents.AGENTS) == 14
    assert agents.AGENTS[0]["name"] == "theme_proposer" and agents.AGENTS[-1]["name"] == "question_varier"
    assert agents.BY_NAME["figure_reader"] == {"name": "figure_reader", "nickname": "Lupa", "doing": "reading a figure"}


def test_every_prompt_file_is_a_valid_template():
    from string import Template
    files = [path for path in agents.HOME.glob("*/*.md") if path.name != "AGENT.md"]
    assert len(files) > 30
    for path in files:
        assert Template(path.read_text(encoding="utf-8")).is_valid(), path


def test_a_missing_or_unused_name_is_an_error():
    with pytest.raises(ValueError, match="missing .'question'."):
        agents.prompt("answer_checker", "check", excerpts="x")
    with pytest.raises(ValueError, match="not used .'extra'."):
        agents.prompt("answer_checker", "check", question="q", excerpts="x", extra="y")


def test_a_missing_file_is_an_error():
    with pytest.raises(FileNotFoundError):
        agents.prompt("answer_checker", "nothing_here")


def test_values_are_taken_as_they_are():
    text = agents.prompt("answer_checker", "check", question="costs $5 ${x} {y}", excerpts="$question")
    assert "costs $5 ${x} {y}" in text and "$question" in text


def read(raw_inner: str) -> str:
    return json.loads(_keep_formulas('{"t": "' + raw_inner + '"}'))["t"]


@pytest.mark.parametrize("raw, read_as", [
    (r"\tilde{x}", r"\tilde{x}"),
    (r"\theta", r"\theta"),
    (r"\text{a}", r"\text{a}"),
    (r"\beta + \frac{a}{b}", r"\beta + \frac{a}{b}"),
    (r"\rho", r"\rho"),
    (r"\nu", r"\nu"),
    (r"a \neq b", r"a \neq b"),
])
def test_a_formula_keeps_its_backslash(raw, read_as):
    assert read(raw) == read_as


@pytest.mark.parametrize("raw, read_as", [
    (r"first\nsecond", "first\nsecond"),
    (r"line\nnew", "line\nnew"),
    (r"a\tb", "a\tb"),
    (r"cell\ttext", "cell\ttext"),
    (r"um\no gato", "um\no gato"),
    (r"um\ne outro", "um\ne outro"),
    (r"um\to gato", "um\to gato"),
    (r"end\r\nnext", "end\r\nnext"),
    (r"say \"hi\"", 'say "hi"'),
    (r"caf\u00e9", "café"),
    (r"\\tilde{x}", r"\tilde{x}"),
    (r"C:\\new\\table", r"C:\new\table"),
])
def test_everything_else_stays_as_written(raw, read_as):
    assert read(raw) == read_as
