import pytest

from amelia_academy import api, runs


@pytest.fixture(autouse=True)
def runs_end_before_the_click_answers(monkeypatch):
    """The stubs answer at once, so a test can read what a run left right after asking for it, on any machine."""
    monkeypatch.setattr(api, "REFUSAL_WAIT", 10)
    runs._runs.clear()
    yield
    runs.wait()
    runs._runs.clear()
