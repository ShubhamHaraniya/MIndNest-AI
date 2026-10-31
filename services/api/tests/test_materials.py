import uuid

from mindnest_worker.pipeline import HttpEmbedder

NOTES = (
    b"# Processes\n\nA process is a program in execution. It has its own address space.\n\n"
    b"# Threads\n\nA thread is a unit of execution inside a process. Threads share memory.\n"
)


def _subject(user, name="Operating Systems"):  # type: ignore[no-untyped-def]
    response = user.post("/subjects", json={"name": name})
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _upload(user, subject_id, name="notes.md", data=NOTES, **form):  # type: ignore[no-untyped-def]
    return user.post(
        f"/subjects/{subject_id}/materials", files={"file": (name, data)}, data=form or None
    )


def test_upload_stores_the_file_and_queues_ingestion(make_user, storage, queue):  # type: ignore[no-untyped-def]
    user = make_user()
    subject_id = _subject(user)
    response = _upload(user, subject_id, kind="note")
    assert response.status_code == 201, response.text
    material = response.json()
    assert material["status"] == "uploaded"
    assert material["kind"] == "note"
    assert material["filename"] == "notes.md"
    assert material["size_bytes"] == len(NOTES)
    assert material["chunk_count"] == 0
    key = f"materials/{user.id}/{material['id']}.md"
    assert storage.objects[key] == NOTES
    assert (material["id"], user.id) in queue.jobs


def test_filenames_are_cleaned_and_never_used_in_storage_keys(make_user, storage):  # type: ignore[no-untyped-def]
    user = make_user()
    subject_id = _subject(user)
    material = _upload(user, subject_id, name="../../etc/passwd.txt", data=b"hello world").json()
    assert material["filename"] == "passwd.txt"
    assert all("passwd" not in key and ".." not in key for key in storage.objects)


def test_upload_rejects_bad_files(make_user):  # type: ignore[no-untyped-def]
    user = make_user()
    subject_id = _subject(user)
    exe = _upload(user, subject_id, name="malware.exe", data=b"MZ\x90\x00")
    assert exe.status_code == 415 and exe.json()["code"] == "unsupported_type"
    disguised = _upload(user, subject_id, name="notes.pdf", data=b"this is not a pdf")
    assert disguised.status_code == 415
    binary_text = _upload(user, subject_id, name="notes.txt", data=b"abc\x00def")
    assert binary_text.status_code == 415
    empty = _upload(user, subject_id, name="empty.txt", data=b"")
    assert empty.status_code == 422 and empty.json()["code"] == "empty_file"
    bad_kind = _upload(user, subject_id, kind="secret")
    assert bad_kind.status_code == 422
    assert user.get(f"/subjects/{subject_id}/materials").json() == []


def test_list_get_and_download(make_user):  # type: ignore[no-untyped-def]
    user = make_user()
    subject_id = _subject(user)
    first = _upload(user, subject_id, name="first.txt", data=b"first file text").json()
    second = _upload(user, subject_id, name="कक्षा नोट्स.txt", data=b"second file text").json()

    listing = user.get(f"/subjects/{subject_id}/materials").json()
    assert [m["id"] for m in listing] == [second["id"], first["id"]]  # newest first
    assert user.get(f"/materials/{first['id']}").json()["filename"] == "first.txt"

    download = user.get(f"/materials/{second['id']}/download")
    assert download.status_code == 200
    assert download.content == b"second file text"
    assert download.headers["content-disposition"].startswith("attachment;")
    assert download.headers["x-content-type-options"] == "nosniff"
    assert user.get(f"/subjects/{subject_id}").json()["material_count"] == 2


def test_ingestion_makes_a_material_searchable_text(make_user, ingest):  # type: ignore[no-untyped-def]
    user = make_user()
    subject_id = _subject(user)
    material = _upload(user, subject_id).json()
    ingest(material["id"], user.id)

    done = user.get(f"/materials/{material['id']}").json()
    assert done["status"] == "ready", done
    assert done["error"] is None
    assert done["chunk_count"] >= 2  # one per Markdown section
    assert done["language"] == "en"
    assert done["stage"] == "embed"


def test_hindi_and_gujarati_material_is_detected(make_user, ingest):  # type: ignore[no-untyped-def]
    user = make_user()
    subject_id = _subject(user)
    hindi = "प्रक्रिया वह प्रोग्राम है जो चल रहा हो। इसका अपना पता स्थान होता है।".encode()
    gujarati = "પ્રક્રિયા એ ચાલી રહેલો પ્રોગ્રામ છે. તેની પોતાની મેમરી હોય છે.".encode()
    h = _upload(user, subject_id, name="hindi.txt", data=hindi).json()
    g = _upload(user, subject_id, name="gujarati.txt", data=gujarati).json()
    ingest(h["id"], user.id)
    ingest(g["id"], user.id)
    assert user.get(f"/materials/{h['id']}").json()["language"] == "hi"
    assert user.get(f"/materials/{g['id']}").json()["language"] == "gu"


def test_a_file_without_readable_text_fails_with_a_code_and_can_be_retried(  # type: ignore[no-untyped-def]
    make_user, ingest, queue
):
    user = make_user()
    subject_id = _subject(user)
    material = _upload(user, subject_id, name="blank.txt", data=b"--- *** ---\n\n 12 \n").json()
    ingest(material["id"], user.id)
    failed = user.get(f"/materials/{material['id']}").json()
    assert failed["status"] == "failed"
    assert failed["error"] == "no_text"
    assert failed["chunk_count"] == 0

    queued_before = len(queue.jobs)
    retried = user.post(f"/materials/{material['id']}/retry")
    assert retried.status_code == 200
    assert retried.json()["status"] == "uploaded" and retried.json()["error"] is None
    assert len(queue.jobs) == queued_before + 1


def test_retry_is_refused_for_a_ready_material(make_user, ingest):  # type: ignore[no-untyped-def]
    user = make_user()
    subject_id = _subject(user)
    material = _upload(user, subject_id).json()
    ingest(material["id"], user.id)
    refused = user.post(f"/materials/{material['id']}/retry")
    assert refused.status_code == 409


def test_unreachable_embedding_service_is_reported_not_crashed(make_user, ingest):  # type: ignore[no-untyped-def]
    user = make_user()
    subject_id = _subject(user)
    material = _upload(user, subject_id).json()
    ingest(material["id"], user.id, embedder=HttpEmbedder("http://127.0.0.1:1", retry_delay=0))
    failed = user.get(f"/materials/{material['id']}").json()
    assert failed["status"] == "failed"
    assert failed["error"] == "embedding_unreachable"
    assert failed["stage"] == "embed"
    assert failed["chunk_count"] == 0


def test_reingesting_replaces_chunks_instead_of_duplicating(make_user, ingest):  # type: ignore[no-untyped-def]
    user = make_user()
    subject_id = _subject(user)
    material = _upload(user, subject_id).json()
    ingest(material["id"], user.id)
    first = user.get(f"/materials/{material['id']}").json()["chunk_count"]
    ingest(material["id"], user.id)
    assert user.get(f"/materials/{material['id']}").json()["chunk_count"] == first


def test_deleting_a_material_removes_its_file_and_chunks(make_user, ingest, storage):  # type: ignore[no-untyped-def]
    user = make_user()
    subject_id = _subject(user)
    material = _upload(user, subject_id).json()
    ingest(material["id"], user.id)
    key = f"materials/{user.id}/{material['id']}.md"
    assert key in storage.objects

    assert user.delete(f"/materials/{material['id']}").status_code == 204
    assert key not in storage.objects
    assert user.get(f"/materials/{material['id']}").status_code == 404
    assert user.get(f"/subjects/{subject_id}").json()["material_count"] == 0
    assert user.delete(f"/materials/{material['id']}").status_code == 404


def test_deleting_a_subject_removes_its_files(make_user, storage):  # type: ignore[no-untyped-def]
    user = make_user()
    subject_id = _subject(user)
    material = _upload(user, subject_id).json()
    key = f"materials/{user.id}/{material['id']}.md"
    impact = user.get(f"/subjects/{subject_id}/delete-impact").json()
    assert impact["materials"] == 1
    assert user.delete(f"/subjects/{subject_id}?confirm=true").status_code == 204
    assert key not in storage.objects
    assert user.get(f"/materials/{material['id']}").status_code == 404


def test_stats_count_only_my_data(make_user, ingest):  # type: ignore[no-untyped-def]
    alice, bob = make_user("Alice"), make_user("Bob")
    subject_id = _subject(alice)
    material = _upload(alice, subject_id).json()
    _upload(alice, subject_id, name="two.txt", data=b"another note about threads")
    ingest(material["id"], alice.id)
    assert alice.get("/stats").json() == {"subjects": 1, "materials": 2, "materials_ready": 1}
    assert bob.get("/stats").json() == {"subjects": 0, "materials": 0, "materials_ready": 0}


# --- cross-user isolation: every material endpoint ----------------------------------------


def test_another_user_cannot_touch_my_materials(make_user, ingest, storage, queue):  # type: ignore[no-untyped-def]
    alice, bob = make_user("Alice"), make_user("Bob")
    subject_id = _subject(alice)
    material = _upload(alice, subject_id).json()
    ingest(material["id"], alice.id)
    mid = material["id"]
    key = f"materials/{alice.id}/{mid}.md"

    assert bob.get(f"/subjects/{subject_id}/materials").status_code == 404
    assert _upload(bob, subject_id, name="mine.txt", data=b"sneaky upload").status_code == 404
    assert bob.get(f"/materials/{mid}").status_code == 404
    assert bob.get(f"/materials/{mid}/download").status_code == 404
    assert bob.post(f"/materials/{mid}/retry").status_code == 404
    assert bob.delete(f"/materials/{mid}").status_code == 404
    assert bob.get(f"/materials/{uuid.uuid4()}").status_code == 404

    # Bob's failed upload must not have left a file or a job behind.
    assert not any(k.startswith(f"materials/{bob.id}/") for k in storage.objects)
    assert not any(owner == bob.id for _, owner in queue.jobs)

    intact = alice.get(f"/materials/{mid}").json()
    assert intact["status"] == "ready" and intact["chunk_count"] >= 2
    assert key in storage.objects


def test_modules_open_times_and_inline_preview(make_user):  # type: ignore[no-untyped-def]
    user = make_user()
    subject_id = _subject(user)
    plain = _upload(user, subject_id, name="week1.txt", data=b"week one text", module="Unit 1 - Processes").json()
    assert plain["module"] == "Unit 1 - Processes" and plain["last_opened_at"] is None
    mid = plain["id"]

    assert user.post(f"/materials/{mid}/open").status_code == 204
    assert user.get(f"/materials/{mid}").json()["last_opened_at"] is not None

    patched = user.patch(f"/materials/{mid}", json={"module": "Unit 2", "kind": "past_paper"})
    assert patched.status_code == 200
    assert patched.json()["module"] == "Unit 2" and patched.json()["kind"] == "past_paper"
    cleared = user.patch(f"/materials/{mid}", json={"module": None})
    assert cleared.json()["module"] is None
    assert user.patch(f"/materials/{mid}", json={"module": "x" * 81}).status_code == 422

    # only types a browser can show safely are ever served inline, and only when asked for
    assert user.get(f"/materials/{mid}/download").headers["content-disposition"].startswith("attachment;")
    shown = user.get(f"/materials/{mid}/download", params={"inline": "true"})
    assert shown.headers["content-disposition"].startswith("inline;")
    assert shown.headers["x-content-type-options"] == "nosniff"
    assert shown.headers["x-frame-options"] == "SAMEORIGIN"  # only our own preview pane may frame it
    assert user.get(f"/materials/{mid}/download").headers["x-frame-options"] == "DENY"
    notes = _upload(user, _subject(user, "Maths"), name="notes.md").json()
    forced = user.get(f"/materials/{notes['id']}/download", params={"inline": "true"})
    assert forced.headers["content-disposition"].startswith("attachment;")  # markdown is never inline


def test_open_and_patch_are_private_to_the_owner(make_user):  # type: ignore[no-untyped-def]
    alice, bob = make_user("Alice"), make_user("Bob")
    mid = _upload(alice, _subject(alice)).json()["id"]
    assert bob.post(f"/materials/{mid}/open").status_code == 404
    assert bob.patch(f"/materials/{mid}", json={"module": "Mine"}).status_code == 404
    assert alice.get(f"/materials/{mid}").json()["module"] is None
