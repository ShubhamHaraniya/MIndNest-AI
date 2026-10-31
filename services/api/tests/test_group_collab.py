"""Study groups beyond the shared library: roles, invitations, notes, discussions and sessions."""

import uuid
from datetime import UTC, datetime, timedelta

from .test_groups import make_group, members, sql


def soon(days=2, hour=15):  # type: ignore[no-untyped-def]
    when = (datetime.now(UTC) + timedelta(days=days)).replace(hour=hour, minute=0, second=0, microsecond=0)
    return when.isoformat()


def invite(user, gid, email, role="member"):  # type: ignore[no-untyped-def]
    return user.post(f"/groups/{gid}/invitations", json={"email": email, "role": role})


def mine(user):  # type: ignore[no-untyped-def]
    response = user.get("/group-invitations")
    assert response.status_code == 200, response.text
    return response.json()


def team(make_user):  # type: ignore[no-untyped-def]
    """An owner, an admin and two members in one group."""
    owner, admin, ann, bob = make_user("Owner"), make_user("Admin"), make_user("Ann"), make_user("Bob")
    group = make_group(owner)
    members(admin, ann, bob, group=group, owner=owner)
    changed = owner.patch(f"/groups/{group['id']}/members/{admin.id}", json={"role": "admin"})
    assert changed.status_code == 200, changed.text
    return owner, admin, ann, bob, group["id"]


# ------------------------------------------------------------------ roles


def test_the_owner_makes_admins_and_takes_it_back(make_user):  # type: ignore[no-untyped-def]
    owner, admin, ann, _, gid = team(make_user)
    detail = owner.get(f"/groups/{gid}").json()
    assert {m["display_name"]: m["role"] for m in detail["members"]} == {
        "Owner": "owner", "Admin": "admin", "Ann": "member", "Bob": "member",
    }
    assert admin.get(f"/groups/{gid}").json()["role"] == "admin" and admin.get(f"/groups/{gid}").json()["join_code"] is None
    back = owner.patch(f"/groups/{gid}/members/{admin.id}", json={"role": "member"}).json()
    assert back["role"] == "member"
    assert ann.patch(f"/groups/{gid}/members/{ann.id}", json={"role": "admin"}).status_code == 403
    assert admin.patch(f"/groups/{gid}/members/{ann.id}", json={"role": "admin"}).status_code == 403
    assert owner.patch(f"/groups/{gid}/members/{owner.id}", json={"role": "member"}).status_code == 403
    assert owner.patch(f"/groups/{gid}/members/{uuid.uuid4()}", json={"role": "admin"}).status_code == 404
    assert owner.patch(f"/groups/{gid}/members/{ann.id}", json={"role": "owner"}).status_code == 422


def test_an_admin_removes_members_but_not_admins_or_the_owner(make_user):  # type: ignore[no-untyped-def]
    owner, admin, ann, bob, gid = team(make_user)
    second = make_user("Second admin")
    members(second, group={"join_code": owner.get(f"/groups/{gid}").json()["join_code"]}, owner=owner)
    owner.patch(f"/groups/{gid}/members/{second.id}", json={"role": "admin"})
    assert admin.delete(f"/groups/{gid}/members/{second.id}").status_code == 403
    assert admin.delete(f"/groups/{gid}/members/{owner.id}").status_code == 403
    assert ann.delete(f"/groups/{gid}/members/{bob.id}").status_code == 403
    assert admin.delete(f"/groups/{gid}/members/{ann.id}").status_code == 204
    assert ann.get(f"/groups/{gid}").status_code == 404
    assert owner.delete(f"/groups/{gid}/members/{second.id}").status_code == 204


def test_an_admin_can_leave_and_can_restore_hidden_files(make_user):  # type: ignore[no-untyped-def]
    owner, admin, ann, _, gid = team(make_user)
    item = sql(
        "INSERT INTO shared_items (group_id, shared_by, filename, storage_key, status) "
        "VALUES (:g, :u, 'n.md', 'shared/x', 'hidden') RETURNING id",
        g=gid, u=ann.id,
    )[0][0]
    assert ann.post(f"/groups/{gid}/items/{item}/restore").status_code == 403
    assert admin.post(f"/groups/{gid}/items/{item}/restore").json() == {"hidden": False}
    assert admin.post(f"/groups/{gid}/leave").status_code == 204
    assert admin.get(f"/groups/{gid}").status_code == 404


# ------------------------------------------------------------------ invitations


def test_an_invited_student_sees_the_invitation_and_joins(make_user):  # type: ignore[no-untyped-def]
    owner, guest = make_user("Asha"), make_user("Guest")
    group = make_group(owner)
    gid = group["id"]
    made = invite(owner, gid, guest.email.upper()).json()
    assert made["email"] == guest.email and made["role"] == "member" and made["invited_by_name"] == "Asha"
    assert [i["email"] for i in owner.get(f"/groups/{gid}/invitations").json()] == [guest.email]

    (waiting,) = mine(guest)
    assert waiting["group_id"] == gid and waiting["group_name"] == group["name"] and waiting["invited_by_name"] == "Asha"
    joined = guest.post(f"/group-invitations/{waiting['id']}/accept").json()
    assert joined["id"] == gid and joined["role"] == "member" and joined["member_count"] == 2
    assert mine(guest) == [] and owner.get(f"/groups/{gid}/invitations").json() == []
    assert guest.post(f"/group-invitations/{waiting['id']}/accept").status_code == 404


def test_the_owner_can_invite_an_admin_but_an_admin_cannot(make_user):  # type: ignore[no-untyped-def]
    owner, admin, _, _, gid = team(make_user)
    guest, helper = make_user("Guest"), make_user("Helper")
    assert invite(admin, gid, guest.email, "admin").status_code == 403
    assert invite(admin, gid, guest.email).status_code == 201
    assert invite(owner, gid, helper.email, "admin").status_code == 201
    (waiting,) = mine(helper)
    assert waiting["role"] == "admin"
    assert helper.post(f"/group-invitations/{waiting['id']}/accept").json()["role"] == "admin"


def test_only_admins_can_invite_and_bad_invitations_are_refused(make_user):  # type: ignore[no-untyped-def]
    owner, _, ann, _, gid = team(make_user)
    guest = make_user("Guest")
    assert invite(ann, gid, guest.email).status_code == 403
    assert ann.get(f"/groups/{gid}/invitations").status_code == 403
    assert invite(owner, gid, "not an address").json()["code"] == "invalid_email"
    assert invite(owner, gid, owner.email).json()["code"] == "already_member"
    assert invite(owner, gid, ann.email).json()["code"] == "already_member"
    assert invite(owner, gid, guest.email).status_code == 201
    assert invite(owner, gid, guest.email.upper()).json()["code"] == "already_invited"
    assert owner.post(f"/groups/{gid}/invitations", json={"email": guest.email, "role": "owner"}).status_code == 422
    assert invite(guest, gid, "x@y.com").status_code == 404  # not in the group: it does not even exist for them


def test_a_withdrawn_or_declined_invitation_cannot_be_accepted(make_user):  # type: ignore[no-untyped-def]
    owner, guest, other = make_user(), make_user("Guest"), make_user("Other")
    gid = make_group(owner)["id"]
    first = invite(owner, gid, guest.email).json()
    assert owner.delete(f"/groups/{gid}/invitations/{first['id']}").status_code == 204
    assert owner.delete(f"/groups/{gid}/invitations/{first['id']}").status_code == 404
    assert mine(guest) == []
    assert invite(owner, gid, guest.email).status_code == 201  # a new one after withdrawing
    (waiting,) = mine(guest)
    assert other.post(f"/group-invitations/{waiting['id']}/accept").status_code == 404  # not their address
    assert other.post(f"/group-invitations/{waiting['id']}/decline").status_code == 404
    assert guest.post(f"/group-invitations/{waiting['id']}/decline").status_code == 204
    assert guest.post(f"/group-invitations/{waiting['id']}/accept").status_code == 404
    assert guest.get(f"/groups/{gid}").status_code == 404


def test_an_invitation_runs_out_and_can_then_be_sent_again(make_user):  # type: ignore[no-untyped-def]
    owner, guest = make_user(), make_user("Guest")
    gid = make_group(owner)["id"]
    made = invite(owner, gid, guest.email).json()
    sql("UPDATE group_invitations SET expires_at = now() - interval '1 day' WHERE id = :i", i=made["id"])
    assert mine(guest) == [] and owner.get(f"/groups/{gid}/invitations").json() == []
    assert guest.post(f"/group-invitations/{made['id']}/accept").status_code == 404
    again = invite(owner, gid, guest.email)
    assert again.status_code == 201 and again.json()["id"] != made["id"]
    assert len(mine(guest)) == 1


# ------------------------------------------------------------------ notes


def test_members_share_notes_and_only_authors_change_them(make_user):  # type: ignore[no-untyped-def]
    owner, admin, ann, bob, gid = team(make_user)
    made = ann.post(f"/groups/{gid}/notes", json={"title": "Week 1", "body": "Processes\nand threads."})
    assert made.status_code == 201, made.text
    note = made.json()
    assert note["mine"] is True and note["author_name"] == "Ann" and note["can_change"] is True
    (listed,) = bob.get(f"/groups/{gid}/notes").json()
    assert listed["excerpt"] == "Processes and threads." and "body" not in listed and listed["mine"] is False
    assert bob.get(f"/groups/{gid}/notes/{note['id']}").json()["body"] == "Processes\nand threads."

    edited = ann.patch(f"/groups/{gid}/notes/{note['id']}", json={"body": "Updated"}).json()
    assert edited["body"] == "Updated" and edited["updated_at"] >= note["updated_at"]
    assert bob.patch(f"/groups/{gid}/notes/{note['id']}", json={"body": "Mine now"}).status_code == 403
    assert admin.patch(f"/groups/{gid}/notes/{note['id']}", json={"title": "Edited by admin"}).status_code == 403
    assert bob.delete(f"/groups/{gid}/notes/{note['id']}").status_code == 403
    assert bob.get(f"/groups/{gid}/notes/{note['id']}").json()["body"] == "Updated"


def test_admins_pin_and_remove_notes(make_user):  # type: ignore[no-untyped-def]
    owner, admin, ann, bob, gid = team(make_user)
    first = ann.post(f"/groups/{gid}/notes", json={"title": "Older"}).json()
    second = bob.post(f"/groups/{gid}/notes", json={"title": "Newer"}).json()
    assert [n["title"] for n in ann.get(f"/groups/{gid}/notes").json()] == ["Newer", "Older"]
    assert ann.patch(f"/groups/{gid}/notes/{first['id']}", json={"pinned": True}).status_code == 403
    assert admin.patch(f"/groups/{gid}/notes/{first['id']}", json={"pinned": True}).json()["pinned"] is True
    assert [n["title"] for n in ann.get(f"/groups/{gid}/notes").json()] == ["Older", "Newer"]
    assert admin.delete(f"/groups/{gid}/notes/{second['id']}").status_code == 204
    assert owner.delete(f"/groups/{gid}/notes/{first['id']}").status_code == 204
    assert ann.get(f"/groups/{gid}/notes").json() == []
    assert ann.get(f"/groups/{gid}/notes/{first['id']}").status_code == 404


def test_notes_are_private_to_the_group_and_checked(make_user):  # type: ignore[no-untyped-def]
    owner, _, ann, _, gid = team(make_user)
    stranger = make_user("Stranger")
    note = ann.post(f"/groups/{gid}/notes", json={"title": "Secret plan"}).json()
    assert stranger.get(f"/groups/{gid}/notes").status_code == 404
    assert stranger.get(f"/groups/{gid}/notes/{note['id']}").status_code == 404
    assert stranger.post(f"/groups/{gid}/notes", json={"title": "x"}).status_code == 404
    other_group = make_group(stranger)["id"]
    assert stranger.get(f"/groups/{other_group}/notes/{note['id']}").status_code == 404
    for bad in ({"title": " "}, {"title": "x" * 121}, {"title": "ok", "body": "b" * 20001}):
        assert ann.post(f"/groups/{gid}/notes", json=bad).status_code == 422, bad
    assert ann.patch(f"/groups/{gid}/notes/{note['id']}", json={"title": None}).status_code == 422
    assert owner.get(f"/groups/{gid}/notes").json()[0]["title"] == "Secret plan"


def test_what_a_former_member_wrote_stays_without_their_name(make_user):  # type: ignore[no-untyped-def]
    owner, _, ann, bob, gid = team(make_user)
    ann.post(f"/groups/{gid}/notes", json={"title": "From Ann"})
    ann.post(f"/groups/{gid}/leave")
    (note,) = bob.get(f"/groups/{gid}/notes").json()
    assert note["title"] == "From Ann" and note["author_name"] is None


# ------------------------------------------------------------------ discussions


def test_a_discussion_collects_replies_and_floats_to_the_top(make_user):  # type: ignore[no-untyped-def]
    owner, _, ann, bob, gid = team(make_user)
    quiet = ann.post(f"/groups/{gid}/threads", json={"title": "Quiet one"}).json()
    busy = bob.post(f"/groups/{gid}/threads", json={"title": "Which chapters?", "body": "For the midterm."}).json()
    assert busy["reply_count"] == 0 and busy["posts"] == [] and busy["mine"] is True
    reply = ann.post(f"/groups/{gid}/threads/{busy['id']}/posts", json={"body": "Chapters 1 to 4."})
    assert reply.status_code == 201 and reply.json()["author_name"] == "Ann" and reply.json()["mine"] is True
    listed = owner.get(f"/groups/{gid}/threads").json()
    assert [t["title"] for t in listed] == ["Which chapters?", "Quiet one"]
    assert listed[0]["reply_count"] == 1 and listed[0]["excerpt"] == "For the midterm."
    full = owner.get(f"/groups/{gid}/threads/{busy['id']}").json()
    assert full["body"] == "For the midterm." and [p["body"] for p in full["posts"]] == ["Chapters 1 to 4."]
    ann.post(f"/groups/{gid}/threads/{quiet['id']}/posts", json={"body": "Anyone?"})
    assert [t["title"] for t in owner.get(f"/groups/{gid}/threads").json()] == ["Quiet one", "Which chapters?"]


def test_replies_can_be_edited_by_their_author_and_deleted_by_admins(make_user):  # type: ignore[no-untyped-def]
    owner, admin, ann, bob, gid = team(make_user)
    thread = ann.post(f"/groups/{gid}/threads", json={"title": "Help"}).json()
    base = f"/groups/{gid}/threads/{thread['id']}/posts"
    post = bob.post(base, json={"body": "First try"}).json()
    edited = bob.patch(f"{base}/{post['id']}", json={"body": "Better answer"}).json()
    assert edited["body"] == "Better answer" and edited["edited_at"] is not None
    assert admin.patch(f"{base}/{post['id']}", json={"body": "Rewritten"}).status_code == 403
    assert ann.delete(f"{base}/{post['id']}").status_code == 403
    assert admin.delete(f"{base}/{post['id']}").status_code == 204
    assert owner.get(f"/groups/{gid}/threads/{thread['id']}").json()["posts"] == []
    assert bob.post(base, json={"body": " "}).status_code == 422


def test_a_locked_discussion_takes_replies_only_from_admins(make_user):  # type: ignore[no-untyped-def]
    owner, admin, ann, bob, gid = team(make_user)
    thread = ann.post(f"/groups/{gid}/threads", json={"title": "Exam rules"}).json()
    path = f"/groups/{gid}/threads/{thread['id']}"
    assert ann.patch(path, json={"locked": True}).status_code == 403
    assert bob.patch(path, json={"pinned": True}).status_code == 403
    assert admin.patch(path, json={"locked": True, "pinned": True}).json()["locked"] is True
    refused = bob.post(f"{path}/posts", json={"body": "Can I?"})
    assert refused.status_code == 409 and refused.json()["code"] == "thread_locked"
    assert admin.post(f"{path}/posts", json={"body": "Rules are final."}).status_code == 201
    assert admin.patch(path, json={"locked": False}).json()["locked"] is False
    assert bob.post(f"{path}/posts", json={"body": "Thanks"}).status_code == 201


def test_only_the_author_or_an_admin_changes_or_deletes_a_discussion(make_user):  # type: ignore[no-untyped-def]
    owner, admin, ann, bob, gid = team(make_user)
    thread = ann.post(f"/groups/{gid}/threads", json={"title": "Mine"}).json()
    path = f"/groups/{gid}/threads/{thread['id']}"
    assert bob.patch(path, json={"title": "Hijacked"}).status_code == 403
    assert admin.patch(path, json={"title": "Hijacked"}).status_code == 403
    renamed = ann.patch(path, json={"title": "Renamed", "body": "New text"}).json()
    assert renamed["title"] == "Renamed" and renamed["edited_at"] is not None
    assert bob.delete(path).status_code == 403
    assert ann.delete(path).status_code == 204
    other = bob.post(f"/groups/{gid}/threads", json={"title": "Other"}).json()
    assert admin.delete(f"/groups/{gid}/threads/{other['id']}").status_code == 204
    assert owner.get(f"/groups/{gid}/threads").json() == []


def test_discussions_are_private_to_the_group(make_user):  # type: ignore[no-untyped-def]
    _, _, ann, _, gid = team(make_user)
    stranger = make_user("Stranger")
    thread = ann.post(f"/groups/{gid}/threads", json={"title": "Private"}).json()
    assert stranger.get(f"/groups/{gid}/threads").status_code == 404
    assert stranger.get(f"/groups/{gid}/threads/{thread['id']}").status_code == 404
    assert stranger.post(f"/groups/{gid}/threads/{thread['id']}/posts", json={"body": "hi"}).status_code == 404
    other_group = make_group(stranger)["id"]
    assert stranger.get(f"/groups/{other_group}/threads/{thread['id']}").status_code == 404


# ------------------------------------------------------------------ study sessions


def test_a_session_is_planned_and_members_say_whether_they_come(make_user):  # type: ignore[no-untyped-def]
    owner, _, ann, bob, gid = team(make_user)
    made = ann.post(
        f"/groups/{gid}/sessions",
        json={"title": "Midterm revision", "description": "Chapters 1-4", "starts_at": soon(), "minutes": 90, "location": "Library, room 3"},
    )
    assert made.status_code == 201, made.text
    session = made.json()
    assert session["state"] == "upcoming" and session["minutes"] == 90 and session["location"] == "Library, room 3"
    assert (session["going"], session["maybe"], session["declined"], session["my_response"]) == (1, 0, 0, "going")
    assert session["mine"] is True and session["can_change"] is True

    path = f"/groups/{gid}/sessions/{session['id']}/rsvp"
    seen = bob.request("PUT", path, json={"response": "maybe"}).json()
    assert (seen["going"], seen["maybe"], seen["my_response"]) == (1, 1, "maybe")
    again = bob.request("PUT", path, json={"response": "going"}).json()
    assert (again["going"], again["maybe"]) == (2, 0)
    assert sorted(a["name"] for a in again["attendees"]) == ["Ann", "Bob"]
    assert owner.request("PUT", path, json={"response": "declined"}).json()["declined"] == 1
    cleared = bob.request("DELETE", path).json()
    assert cleared["my_response"] is None and cleared["going"] == 1
    assert bob.request("PUT", path, json={"response": "perhaps"}).status_code == 422


def test_sessions_are_checked(make_user):  # type: ignore[no-untyped-def]
    _, _, ann, _, gid = team(make_user)
    good = {"title": "Study", "starts_at": soon()}
    assert ann.post(f"/groups/{gid}/sessions", json=good).status_code == 201
    yesterday = (datetime.now(UTC) - timedelta(days=1)).isoformat()
    assert ann.post(f"/groups/{gid}/sessions", json={**good, "title": "Late", "starts_at": yesterday}).json()["code"] == "session_in_past"
    naive = (datetime.now(UTC) + timedelta(days=3)).replace(tzinfo=None).isoformat()
    assert ann.post(f"/groups/{gid}/sessions", json={**good, "title": "Naive", "starts_at": naive}).status_code == 422
    for bad in ({"title": " "}, {"minutes": 5}, {"minutes": 9999}, {"starts_at": "someday"}, {"location": "x" * 301}):
        assert ann.post(f"/groups/{gid}/sessions", json={**good, "title": "Other", **bad}).status_code == 422, bad
    twin = ann.post(f"/groups/{gid}/sessions", json={**good, "title": "STUDY"})
    assert twin.status_code == 409 and twin.json()["code"] == "session_duplicate"


def test_the_organiser_or_an_admin_changes_cancels_and_deletes_a_session(make_user):  # type: ignore[no-untyped-def]
    owner, admin, ann, bob, gid = team(make_user)
    session = ann.post(f"/groups/{gid}/sessions", json={"title": "Study", "starts_at": soon()}).json()
    path = f"/groups/{gid}/sessions/{session['id']}"
    assert bob.patch(path, json={"title": "Hijack"}).status_code == 403
    assert bob.delete(path).status_code == 403
    moved = ann.patch(path, json={"starts_at": soon(3, 10), "location": "Cafe"}).json()
    assert moved["location"] == "Cafe" and moved["starts_at"] != session["starts_at"]
    cancelled = admin.patch(path, json={"status": "cancelled"}).json()
    assert cancelled["state"] == "cancelled" and cancelled["status"] == "cancelled"
    closed = bob.request("PUT", f"{path}/rsvp", json={"response": "going"})
    assert closed.status_code == 409 and closed.json()["code"] == "session_closed"
    assert ann.patch(path, json={"status": "scheduled"}).json()["state"] == "upcoming"
    assert ann.patch(path, json={"minutes": None}).status_code == 422
    assert owner.delete(path).status_code == 204
    assert ann.get(path).status_code == 404


def test_a_session_ends_up_in_the_past_and_stops_taking_answers(make_user):  # type: ignore[no-untyped-def]
    _, _, ann, bob, gid = team(make_user)
    session = ann.post(f"/groups/{gid}/sessions", json={"title": "Study", "starts_at": soon(), "minutes": 30}).json()
    sql("UPDATE group_sessions SET starts_at = now() - interval '2 hours' WHERE id = :i", i=session["id"])
    now = ann.get(f"/groups/{gid}/sessions/{session['id']}").json()
    assert now["state"] == "past"
    assert bob.request("PUT", f"/groups/{gid}/sessions/{session['id']}/rsvp", json={"response": "going"}).status_code == 409
    sql("UPDATE group_sessions SET starts_at = now() - interval '10 minutes' WHERE id = :i", i=session["id"])
    assert ann.get(f"/groups/{gid}/sessions/{session['id']}").json()["state"] == "ongoing"


def test_a_session_goes_on_my_calendar_once(make_user):  # type: ignore[no-untyped-def]
    _, _, ann, bob, gid = team(make_user)
    group_name = ann.get(f"/groups/{gid}").json()["name"]
    session = ann.post(
        f"/groups/{gid}/sessions",
        json={"title": "Revision", "starts_at": soon(2, 15), "minutes": 60, "location": "Library"},
    ).json()
    path = f"/groups/{gid}/sessions/{session['id']}/calendar"
    first = bob.post(path)
    assert first.status_code == 200, first.text
    added = first.json()
    assert added["already"] is False and added["start_time"] == "15:00"
    again = bob.post(path).json()
    assert again["already"] is True and again["event_id"] == added["event_id"]

    day = added["day"]
    events = bob.get("/calendar", params={"from": day, "to": day}).json()["events"]
    (event,) = [e for e in events if e["kind"] == "event"]
    assert event["title"] == f"{group_name}: Revision" and event["start_time"] == "15:00" and event["minutes"] == 60
    assert "Library" in event["notes"]
    assert [e for e in ann.get("/calendar", params={"from": day, "to": day}).json()["events"] if e["kind"] == "event"] == []


def test_sessions_are_private_to_the_group(make_user):  # type: ignore[no-untyped-def]
    _, _, ann, _, gid = team(make_user)
    stranger = make_user("Stranger")
    session = ann.post(f"/groups/{gid}/sessions", json={"title": "Study", "starts_at": soon()}).json()
    base = f"/groups/{gid}/sessions"
    assert stranger.get(base).status_code == 404
    assert stranger.get(f"{base}/{session['id']}").status_code == 404
    assert stranger.post(base, json={"title": "x", "starts_at": soon()}).status_code == 404
    assert stranger.request("PUT", f"{base}/{session['id']}/rsvp", json={"response": "going"}).status_code == 404
    assert stranger.post(f"{base}/{session['id']}/calendar").status_code == 404
