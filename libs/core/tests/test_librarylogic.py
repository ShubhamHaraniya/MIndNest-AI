from mindnest_core.librarylogic import (
    DOC_TYPES,
    is_wider,
    material_kind,
    status_for_owner_change,
)


def test_private_is_a_draft_institution_is_published_public_waits_for_review():
    assert status_for_owner_change("private") == "draft"
    assert status_for_owner_change("institution") == "published"
    assert status_for_owner_change("public") == "pending_review"


def test_widening_visibility_is_detected():
    assert is_wider("private", "institution")
    assert is_wider("institution", "public")
    assert is_wider("private", "public")
    assert not is_wider("public", "institution")
    assert not is_wider("institution", "institution")


def test_every_document_type_maps_to_a_material_kind():
    kinds = {material_kind(doc_type) for doc_type in DOC_TYPES}
    assert kinds <= {"material", "past_paper", "note"}
    assert material_kind("past_paper") == "past_paper"
    assert material_kind("notes") == "note"
    assert material_kind("textbook") == "material"
