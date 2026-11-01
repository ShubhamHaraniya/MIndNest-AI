"""A file attached to a chat must reach whichever agent answers, and the router must know about it.

Found when a student attached a photo and asked "Tell me about this photo": the router picked the
Materials agent, which never saw the attachment and answered that it cannot view photos."""

from types import SimpleNamespace

from mindnest_api.agent.registry import base_prompt
from mindnest_api.agent.router import build_router_prompt

ATTACHED = "<attachment name=\"notes.png\">ReAct vs Plan-Execute</attachment>"


def _ctx(attachment_text: str) -> SimpleNamespace:
    return SimpleNamespace(
        user=SimpleNamespace(answer_language="en"), canary="CANARY-1", attachment_text=attachment_text,
        subjects=[], subject_id=None,
    )


def test_every_agent_prompt_includes_the_attached_files() -> None:
    prompt = base_prompt(_ctx(ATTACHED), "materials agent", "role")
    assert "FILES THE STUDENT ATTACHED TO THIS CHAT" in prompt
    assert "ReAct vs Plan-Execute" in prompt


def test_prompt_is_unchanged_without_attachments() -> None:
    assert "ATTACHED" not in base_prompt(_ctx(""), "materials agent", "role")


def test_router_is_told_about_attachments_and_sends_them_to_study() -> None:
    prompt = build_router_prompt("- study: x", _ctx(ATTACHED))
    assert "FILES ATTACHED TO THIS CHAT" in prompt
    assert 'pick "study"' in prompt


def test_router_prompt_is_unchanged_without_attachments() -> None:
    assert "FILES ATTACHED" not in build_router_prompt("- study: x", _ctx(""))
