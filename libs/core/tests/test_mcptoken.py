"""The short-lived, single-use tokens that let the API ask the calendar server for one thing."""

import pytest
from mindnest_core.mcptoken import MAX_TTL, ReplayGuard, TokenError, args_hash, check_call, mint, verify

KEY = "k" * 40
USER = "11111111-1111-1111-1111-111111111111"
ARGS = {"event_id": "abc", "event": {"summary": "Exam", "minutes": 60}}


def code_of(call):
    with pytest.raises(TokenError) as caught:
        call()
    return caught.value.code


def test_a_good_token_names_the_user_the_tool_and_the_arguments():
    claims = verify(KEY, mint(KEY, USER, "create_event", ARGS, now=1000.0), now=1010.0)
    assert (claims.user_id, claims.tool) == (USER, "create_event")
    check_call(claims, "create_event", ARGS)


def test_the_argument_fingerprint_ignores_key_order_but_not_values():
    assert args_hash({"a": 1, "b": 2}) == args_hash({"b": 2, "a": 1})
    assert args_hash({"a": 1}) != args_hash({"a": 2})


def test_a_token_is_for_one_tool_and_one_set_of_arguments():
    claims = verify(KEY, mint(KEY, USER, "create_event", ARGS))
    assert code_of(lambda: check_call(claims, "delete_event", ARGS)) == "wrong_tool"
    assert code_of(lambda: check_call(claims, "create_event", {**ARGS, "event_id": "other"})) == "wrong_arguments"


def test_an_expired_token_is_refused():
    token = mint(KEY, USER, "t", {}, ttl=60, now=1000.0)
    assert verify(KEY, token, now=1059.0)
    assert code_of(lambda: verify(KEY, token, now=1061.0)) == "expired_token"


def test_the_lifetime_is_capped():
    claims = verify(KEY, mint(KEY, USER, "t", {}, ttl=10_000, now=0.0), now=1.0)
    assert claims.expires_at <= MAX_TTL


def test_tampering_and_other_keys_are_refused():
    token = mint(KEY, USER, "t", {})
    body, _, signature = token.partition(".")
    forged_body = mint(KEY, "22222222-2222-2222-2222-222222222222", "t", {}).partition(".")[0]
    assert code_of(lambda: verify(KEY, f"{forged_body}.{signature}")) == "bad_token"
    assert code_of(lambda: verify("another key " * 4, token)) == "bad_token"
    assert code_of(lambda: verify(KEY, f"{body}.AAAA")) == "bad_token"


@pytest.mark.parametrize("junk", [None, "", "abc", "a.b.c", "é.é", "."])
def test_junk_is_refused_without_crashing(junk):
    assert code_of(lambda: verify(KEY, junk)) in ("missing_token", "bad_token")


def test_a_token_works_once():
    guard = ReplayGuard()
    claims = verify(KEY, mint(KEY, USER, "t", {}))
    guard.use(claims)
    assert code_of(lambda: guard.use(claims)) == "replayed_token"


def test_the_replay_list_forgets_expired_tokens_and_cannot_be_flooded():
    guard = ReplayGuard(max_items=2)
    a, b, c = (verify(KEY, mint(KEY, USER, "t", {}, ttl=10, now=100.0), now=100.0) for _ in range(3))
    guard.use(a, now=100.0)
    guard.use(b, now=100.0)
    assert code_of(lambda: guard.use(c, now=105.0)) == "busy"
    guard.use(c, now=200.0)  # a and b have expired and are forgotten
