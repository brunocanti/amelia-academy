"""The group of agents: every task the model does has one folder here, with a technical name and a nickname.

An agent is a fixed job: its prompt, its schema and the checks on its output. None chooses what runs next;
the order stays in the code, so a read gives the same steps every time. The console shows work under these names.

The words live in the folders and the code reads them from there. README.md says how to change one.
"""

from pathlib import Path
from string import Template

HOME = Path(__file__).parent


def _read(agent: str, name: str) -> str:
    text = (HOME / agent / f"{name}.md").read_text(encoding="utf-8")
    return text[:-1] if text.endswith("\n") else text


def prompt(agent: str, name: str, **values) -> str:
    """Read on every call, so a changed prompt counts from the next call. A name left out or never used is an error, not a silent gap."""
    template = Template(_read(agent, name))
    wanted = set(template.get_identifiers())
    if wanted != set(values):
        raise ValueError(f"{agent}/{name}.md: missing {sorted(wanted - set(values))}, not used {sorted(set(values) - wanted)}")
    return template.substitute(values)


def lines(agent: str, name: str) -> tuple[str, ...]:
    return tuple(line for line in _read(agent, name).splitlines() if line.strip())


def table(agent: str, name: str) -> dict[str, str]:
    """A file of `key: value` lines."""
    return dict(line.split(": ", 1) for line in lines(agent, name))


def _card(folder: Path) -> dict:
    head = (folder / "AGENT.md").read_text(encoding="utf-8").split("---")[1]
    return dict(line.split(": ", 1) for line in head.strip().splitlines())


_cards = sorted((_card(path.parent) for path in HOME.glob("*/AGENT.md")), key=lambda card: int(card["order"]))
AGENTS = [{"name": card["name"], "nickname": card["nickname"], "doing": card["doing"]} for card in _cards]
BY_NAME = {agent["name"]: agent for agent in AGENTS}
