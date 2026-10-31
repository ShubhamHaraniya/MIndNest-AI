from mindnest_core.grouplogic import (
    ALPHABET,
    CODE_LENGTH,
    HIDE_AT_REPORTS,
    display_code,
    new_join_code,
    normalize_code,
)


def test_new_codes_have_the_right_shape_and_differ():
    codes = {new_join_code() for _ in range(200)}
    assert len(codes) == 200
    assert all(len(c) == CODE_LENGTH and set(c) <= set(ALPHABET) for c in codes)


def test_the_alphabet_has_no_lookalike_characters():
    assert not set("0O1IL") & set(ALPHABET)


def test_typed_codes_are_forgiven_for_case_spaces_and_dashes():
    code = new_join_code()
    shown = display_code(code)
    assert shown.count("-") == 1 and shown.replace("-", "") == code
    for typed in (shown, shown.lower(), f"  {code.lower()} ", shown.replace("-", " "), shown.replace("-", "_")):
        assert normalize_code(typed) == code


def test_things_that_cannot_be_codes_are_rejected():
    for bad in ("", "short", "A" * 11, "ABCDE-FGH0O", "ABCDE FGH!?", "ÀBCDEFGH23"):
        assert normalize_code(bad) is None


def test_the_hide_threshold_needs_more_than_one_report():
    assert HIDE_AT_REPORTS >= 2


# ------------------------------------------------------------------ roles


def test_admins_and_owners_run_the_group_members_do_not():
    from mindnest_core.grouplogic import is_admin

    assert is_admin("owner") and is_admin("admin")
    assert not is_admin("member") and not is_admin(None) and not is_admin("")


def test_who_may_remove_whom():
    from mindnest_core.grouplogic import can_remove_member

    assert can_remove_member("owner", "admin") and can_remove_member("owner", "member")
    assert not can_remove_member("owner", "owner")
    assert can_remove_member("admin", "member")
    assert not can_remove_member("admin", "admin") and not can_remove_member("admin", "owner")
    assert not can_remove_member("member", "member") and not can_remove_member(None, "member")


def test_only_the_owner_changes_roles_and_never_their_own():
    from mindnest_core.grouplogic import can_set_role

    assert can_set_role("owner", "member", "admin") and can_set_role("owner", "admin", "member")
    assert not can_set_role("owner", "owner", "member")
    assert not can_set_role("owner", "member", "owner")  # there is one owner
    assert not can_set_role("admin", "member", "admin") and not can_set_role("member", "member", "admin")


def test_the_author_or_an_admin_may_change_what_was_written():
    from mindnest_core.grouplogic import can_change

    assert can_change("member", True) and can_change("owner", False) and can_change("admin", False)
    assert not can_change("member", False)


# ------------------------------------------------------------------ invitations


def test_email_addresses_are_compared_in_lower_case_and_junk_is_refused():
    from mindnest_core.grouplogic import normalize_email

    assert normalize_email("  Asha.Patel@College.EDU ") == "asha.patel@college.edu"
    for bad in ("", "no-at-sign", "two@@signs.com", "spaces in@x.com", "a@b", "a@b.c", "x" * 250 + "@y.com"):
        assert normalize_email(bad) is None, bad


# ------------------------------------------------------------------ sessions


def test_a_session_moves_from_upcoming_to_ongoing_to_past_unless_cancelled():
    from datetime import UTC, datetime, timedelta

    from mindnest_core.grouplogic import session_state

    start = datetime(2026, 11, 5, 15, 0, tzinfo=UTC)
    before, during, after = start - timedelta(minutes=1), start + timedelta(minutes=30), start + timedelta(minutes=60)
    assert session_state(start, 60, "scheduled", before) == "upcoming"
    assert session_state(start, 60, "scheduled", start) == "ongoing"
    assert session_state(start, 60, "scheduled", during) == "ongoing"
    assert session_state(start, 60, "scheduled", after) == "past"
    for moment in (before, during, after):
        assert session_state(start, 60, "cancelled", moment) == "cancelled"


def test_rsvps_are_counted_and_unknown_answers_ignored():
    from mindnest_core.grouplogic import rsvp_counts

    assert rsvp_counts([]) == {"going": 0, "maybe": 0, "declined": 0}
    assert rsvp_counts(["going", "going", "maybe", "declined", "nonsense"]) == {"going": 2, "maybe": 1, "declined": 1}


def test_an_excerpt_is_one_short_line():
    from mindnest_core.grouplogic import excerpt

    assert excerpt("First line.\n\n  Second   line.") == "First line. Second line."
    long = excerpt("word " * 100, 40)
    assert len(long) <= 40 and long.endswith("…")
    assert excerpt("") == ""
