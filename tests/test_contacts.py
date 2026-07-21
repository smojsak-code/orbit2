"""
scripts/contacts.py tests (Contacts Phase 1 / R3-T01).

Covers the identity-resolution decision logic (pure functions, no
filesystem) and the CLI workflow (find-or-create / merge / set-canonical-name
/ add-evidence / summary) against the isolated fixture register.
"""
from types import SimpleNamespace

import contacts as contacts_mod


# ---------------------------------------------------------------------------
# Name similarity / matching (pure functions)
# ---------------------------------------------------------------------------

def test_normalize_name_strips_punctuation_and_case():
    assert contacts_mod.normalize_name("Dr. Jon Smith Jr.") == "dr jon smith jr"
    assert contacts_mod.normalize_name("  Jon   Smith  ") == "jon smith"


def test_name_similarity_identical_is_1():
    assert contacts_mod.name_similarity("Jon Smith", "Jon Smith") == 1.0


def test_name_similarity_blank_is_0():
    assert contacts_mod.name_similarity("", "Jon Smith") == 0.0
    assert contacts_mod.name_similarity("Jon Smith", "") == 0.0


def test_find_candidate_matches_exact_email_wins_regardless_of_name(patched_contacts):
    contacts = [{
        "contact_id": "CONT-0001", "canonical_name": "A Completely Different Name",
        "raw_extracted_name": "A Completely Different Name", "company": "Acme",
        "email": "person@acme.com", "status": "confirmed",
    }]
    candidates = contacts_mod.find_candidate_matches("Someone Else Entirely", email="person@acme.com", contacts=contacts)
    assert candidates[0]["contact_id"] == "CONT-0001"
    assert candidates[0]["score"] == 1.0
    assert "exact email match" in candidates[0]["reasons"][0]


def test_find_candidate_matches_excludes_merged_and_archived(patched_contacts):
    contacts = [
        {"contact_id": "CONT-0001", "canonical_name": "Jon Smith", "raw_extracted_name": "Jon Smith", "status": "merged", "company": "", "email": ""},
        {"contact_id": "CONT-0002", "canonical_name": "Jon Smith", "raw_extracted_name": "Jon Smith", "status": "archived", "company": "", "email": ""},
    ]
    candidates = contacts_mod.find_candidate_matches("Jon Smith", contacts=contacts)
    assert candidates == []


def test_match_contact_auto_matches_on_name_plus_company_and_title(patched_contacts):
    contacts = [{
        "contact_id": "CONT-0001", "canonical_name": "Jonathan Smith", "raw_extracted_name": "Jonathan Smith",
        "company": "Acme", "title": "VP Sales", "status": "confirmed", "email": "",
    }]
    decision = contacts_mod.match_contact("Jon Smith", company="Acme", title="VP Sales", contacts=contacts)
    assert decision["decision"] == "matched"
    assert decision["contact_id"] == "CONT-0001"


def test_match_contact_needs_review_on_name_alone(patched_contacts):
    contacts = [{
        "contact_id": "CONT-0001", "canonical_name": "Jonathon Smyth", "raw_extracted_name": "Jonathon Smyth",
        "company": "", "title": "", "status": "confirmed", "email": "",
    }]
    decision = contacts_mod.match_contact("Jonathan Smith", contacts=contacts)
    assert decision["decision"] == "needs_review"
    assert decision["contact_id"] == "CONT-0001"


def test_match_contact_new_when_nothing_similar(patched_contacts):
    contacts = [{
        "contact_id": "CONT-0001", "canonical_name": "Completely Different Person",
        "raw_extracted_name": "Completely Different Person", "company": "", "title": "", "status": "confirmed", "email": "",
    }]
    decision = contacts_mod.match_contact("Zzyzx Q. Nobody", contacts=contacts)
    assert decision["decision"] == "new"


# ---------------------------------------------------------------------------
# CLI workflow
# ---------------------------------------------------------------------------

def test_find_or_create_matches_existing_fixture_contact_by_alias_spelling(patched_contacts):
    """tests/fixtures/data/contacts.csv has 'Jamie Chen' (canonical) with
    raw_extracted_name 'Jaime Chen' at TestVendor as 'Director of
    Partnerships' — a new mention of 'Jaime Chen' at the same company/title
    should auto-match, not create a duplicate."""
    decision = contacts_mod.cmd_find_or_create(SimpleNamespace(
        name="Jaime Chen", company="TestVendor", title="Director of Partnerships",
        email=None, vendor=None, visibility=None,
    ))
    assert decision["decision"] == "matched"
    assert decision["contact_id"] == "CONT-0001"
    assert len(contacts_mod.read_contacts()) == 1, "must not have created a duplicate"


def test_find_or_create_creates_new_provisional_contact(patched_contacts):
    decision = contacts_mod.cmd_find_or_create(SimpleNamespace(
        name="Someone Brand New", company=None, title=None, email=None, vendor=None, visibility=None,
    ))
    assert decision["decision"] == "new"
    contacts = contacts_mod.read_contacts()
    new_row = next(r for r in contacts if r["contact_id"] == decision["contact_id"])
    assert new_row["status"] == "provisional"
    assert new_row["canonical_name"] == "Someone Brand New"
    assert new_row["relationship_owner"] == "Test User"


def test_set_canonical_name_preserves_prior_name_as_alias(patched_contacts):
    contacts_mod.cmd_set_canonical_name(SimpleNamespace(contact_id="CONT-0001", name="Jonathan Chen-Michaels"))
    contacts = {r["contact_id"]: r for r in contacts_mod.read_contacts()}
    assert contacts["CONT-0001"]["canonical_name"] == "Jonathan Chen-Michaels"

    aliases = contacts_mod.read_aliases()
    assert any(a["contact_id"] == "CONT-0001" and a["alias"] == "Jamie Chen" and a["alias_type"] == "prior_name" for a in aliases)


def test_add_evidence_updates_current_profile_when_confidence_at_least_equal(patched_contacts):
    contacts_mod.cmd_add_evidence(SimpleNamespace(
        contact_id="CONT-0001", field="title", value="VP of Partnerships",
        source_type="transcript", source_ref="meeting-1", confidence="confirmed",
        sensitivity="standard", rationale=None, meeting_ref=None, extracted_at=None,
    ))
    contacts = {r["contact_id"]: r for r in contacts_mod.read_contacts()}
    assert contacts["CONT-0001"]["title"] == "VP of Partnerships"

    evidence = contacts_mod.read_evidence()
    old = next(e for e in evidence if e["field"] == "title" and e["value"] == "Director of Partnerships")
    assert old["superseded_by"], "the prior evidence for this field must be marked superseded, not deleted"
    new = next(e for e in evidence if e["field"] == "title" and e["value"] == "VP of Partnerships")
    assert not new["superseded_by"]


def test_add_evidence_does_not_downgrade_current_profile_with_lower_confidence(patched_contacts):
    """Fixture's existing title evidence is confidence=confirmed. A new
    low_confidence guess at a different title must not overwrite it."""
    contacts_mod.cmd_add_evidence(SimpleNamespace(
        contact_id="CONT-0001", field="title", value="Maybe a manager now?",
        source_type="manual_note", source_ref=None, confidence="low_confidence",
        sensitivity="standard", rationale=None, meeting_ref=None, extracted_at=None,
    ))
    contacts = {r["contact_id"]: r for r in contacts_mod.read_contacts()}
    assert contacts["CONT-0001"]["title"] == "Director of Partnerships", "lower-confidence evidence must not overwrite the current value"

    evidence = contacts_mod.read_evidence()
    old = next(e for e in evidence if e["field"] == "title" and e["value"] == "Director of Partnerships")
    assert not old["superseded_by"], "the higher-confidence evidence must remain current"


def test_add_evidence_with_no_contacts_csv_column_only_logs(patched_contacts):
    """A field like 'commitment' has no direct contacts.csv column — it
    should be logged but never attempt (or claim) to update the profile."""
    contacts_mod.cmd_add_evidence(SimpleNamespace(
        contact_id="CONT-0001", field="commitment", value="Will send the roadmap by Friday",
        source_type="transcript", source_ref=None, confidence="confirmed",
        sensitivity="standard", rationale=None, meeting_ref=None, extracted_at=None,
    ))
    evidence = contacts_mod.read_evidence()
    assert any(e["field"] == "commitment" and e["value"] == "Will send the roadmap by Friday" for e in evidence)


def test_merge_preserves_losing_contact_and_creates_alias_on_survivor(patched_contacts):
    contacts_mod.cmd_create(SimpleNamespace(
        name="J. Chen", title="Director of Partnerships", company="TestVendor",
        email=None, affiliation=None, vendor=None, visibility=None,
    ))
    contacts = contacts_mod.read_contacts()
    duplicate_id = next(r["contact_id"] for r in contacts if r["canonical_name"] == "J. Chen")

    contacts_mod.cmd_merge(SimpleNamespace(losing_id=duplicate_id, surviving_id="CONT-0001", reason="test merge"))

    contacts = {r["contact_id"]: r for r in contacts_mod.read_contacts()}
    assert contacts[duplicate_id]["status"] == "merged"
    assert contacts[duplicate_id]["merged_into"] == "CONT-0001"
    assert contacts["CONT-0001"]["status"] != "merged", "the surviving contact must be untouched by the merge status-wise"

    aliases = contacts_mod.read_aliases()
    assert any(a["contact_id"] == "CONT-0001" and a["alias"] == "J. Chen" for a in aliases)

    assert contacts_mod.resolve_canonical(duplicate_id, contacts) == "CONT-0001"
    assert contacts_mod.resolve_canonical("CONT-0001", contacts) == "CONT-0001"


def test_merge_into_self_is_rejected(patched_contacts):
    """Intentional-failure case: merging a contact into itself must be
    rejected rather than silently corrupting the merged_into chain."""
    contacts_before = contacts_mod.read_contacts()
    contacts_mod.cmd_merge(SimpleNamespace(losing_id="CONT-0001", surviving_id="CONT-0001", reason="test"))
    contacts_after = contacts_mod.read_contacts()
    assert contacts_before == contacts_after, "a self-merge attempt must not alter the register at all"


# ---------------------------------------------------------------------------
# Profile summary
# ---------------------------------------------------------------------------

def test_compute_profile_summary_separates_confirmed_probable_and_subjective(patched_contacts):
    contacts_mod.cmd_add_evidence(SimpleNamespace(
        contact_id="CONT-0001", field="communication_style", value="Prefers email over calls",
        source_type="meeting_note", source_ref=None, confidence="probable",
        sensitivity="subjective", rationale=None, meeting_ref=None, extracted_at=None,
    ))
    contacts = contacts_mod.read_contacts()
    evidence = contacts_mod.read_evidence()
    aliases = contacts_mod.read_aliases()
    summary = contacts_mod.compute_profile_summary("CONT-0001", contacts, evidence, aliases)

    assert any("Director of Partnerships" in line for line in summary["confirmed"])
    assert any("email over calls" in line for line in summary["subjective"])
    assert summary["subjective"] and not any("email over calls" in line for line in summary["confirmed"])


def test_compute_profile_summary_flags_missing_information(patched_contacts):
    contacts = contacts_mod.read_contacts()
    evidence = contacts_mod.read_evidence()
    aliases = contacts_mod.read_aliases()
    summary = contacts_mod.compute_profile_summary("CONT-0001", contacts, evidence, aliases)
    assert "email address" in summary["missing"], "fixture contact has no email on file"


def test_compute_profile_summary_states_alias_history_explicitly(patched_contacts):
    contacts_mod.cmd_set_canonical_name(SimpleNamespace(contact_id="CONT-0001", name="Jonathan Chen-Michaels"))
    contacts = contacts_mod.read_contacts()
    evidence = contacts_mod.read_evidence()
    aliases = contacts_mod.read_aliases()
    summary = contacts_mod.compute_profile_summary("CONT-0001", contacts, evidence, aliases)
    # raw_extracted_name in the fixture is 'Jaime Chen' (deliberately a
    # different spelling from canonical_name 'Jamie Chen') — the "originally
    # extracted as X" note is always built from raw_extracted_name, not
    # whatever the canonical name happened to be before this rename.
    assert "originally extracted as 'jaime chen'" in summary["aliases_note"].lower()
    assert "jonathan chen-michaels" in summary["aliases_note"].lower()


def test_compute_profile_summary_unknown_contact_does_not_crash(patched_contacts):
    contacts = contacts_mod.read_contacts()
    summary = contacts_mod.compute_profile_summary("CONT-9999", contacts, [], [])
    assert "No contact found" in summary["text"]


# ---------------------------------------------------------------------------
# Phase 2: record_evidence_row / resolve_or_create_for_ingest (pure, no I/O)
# ---------------------------------------------------------------------------

def test_record_evidence_row_updates_profile_and_supersedes_prior():
    contacts_map = {"CONT-0001": {"contact_id": "CONT-0001", "title": "Old Title", "last_interaction_at": "2026-01-01"}}
    evidence = [{
        "evidence_id": "CEV-0001", "contact_id": "CONT-0001", "field": "title", "value": "Old Title",
        "confidence": "confirmed", "extracted_at": "2026-01-01", "superseded_by": "",
    }]
    result = contacts_mod.record_evidence_row(
        contacts_map, evidence, contact_id="CONT-0001", field="title", value="New Title",
        source_type="transcript", confidence="confirmed", extracted_at="2026-07-21",
    )
    assert result["applied_to_profile"] is True
    assert result["column"] == "title"
    assert contacts_map["CONT-0001"]["title"] == "New Title"
    assert evidence[0]["superseded_by"] == result["evidence_id"]
    assert len(evidence) == 2, "must append, never remove, a row"


def test_record_evidence_row_no_column_never_touches_profile():
    contacts_map = {"CONT-0001": {"contact_id": "CONT-0001", "last_interaction_at": ""}}
    evidence = []
    result = contacts_mod.record_evidence_row(
        contacts_map, evidence, contact_id="CONT-0001", field="topic_discussed", value="Renewal timeline",
        source_type="meeting_note", confidence="probable", extracted_at="2026-07-21",
    )
    assert result["applied_to_profile"] is False
    assert result["column"] is None
    assert len(evidence) == 1


def test_resolve_or_create_for_ingest_matched_reuses_existing_contact_id(patched_contacts):
    contacts = contacts_mod.read_contacts()
    contacts_map = contacts_mod.contacts_by_id(contacts)
    res = contacts_mod.resolve_or_create_for_ingest(
        "Jaime Chen", contacts, contacts_map, company="TestVendor", title="Director of Partnerships",
    )
    assert res["decision"] == "matched"
    assert res["contact_id"] == "CONT-0001"
    assert len(contacts) == 1, "a matched person must not create a new row"


def test_resolve_or_create_for_ingest_needs_review_creates_new_contact_not_a_merge(patched_contacts):
    contacts = contacts_mod.read_contacts()
    contacts_map = contacts_mod.contacts_by_id(contacts)
    res = contacts_mod.resolve_or_create_for_ingest("Jamie Chung", contacts, contacts_map)
    assert res["decision"] == "needs_review"
    assert res["candidate_id"] == "CONT-0001"
    assert res["contact_id"] != "CONT-0001", "needs_review must get its OWN new contact_id, never silently merged"
    assert res["contact_id"] in contacts_map
    assert len(contacts) == 2


def test_resolve_or_create_for_ingest_new_creates_provisional_contact(patched_contacts):
    contacts = contacts_mod.read_contacts()
    contacts_map = contacts_mod.contacts_by_id(contacts)
    res = contacts_mod.resolve_or_create_for_ingest("Someone Entirely New", contacts, contacts_map)
    assert res["decision"] == "new"
    assert contacts_map[res["contact_id"]]["status"] == "provisional"


# ---------------------------------------------------------------------------
# Phase 2: cmd_ingest (batch document ingestion)
# ---------------------------------------------------------------------------

def _write_payload(tmp_path, payload, name="payload.json"):
    import json
    path = tmp_path / name
    path.write_text(json.dumps(payload))
    return str(path)


def test_ingest_matched_person_records_evidence_without_new_contact(patched_contacts, tmp_path):
    payload = {
        "source_type": "meeting_note", "source_ref": "QBR notes", "extracted_at": "2026-07-21",
        "people": [{
            "name": "Jaime Chen", "company": "TestVendor", "title": "Director of Partnerships",
            "evidence": [{"field": "topic_discussed", "value": "Renewal timeline", "confidence": "probable"}],
        }],
    }
    path = _write_payload(tmp_path, payload)
    contacts_mod.cmd_ingest(SimpleNamespace(file=path, dry_run=False))

    contacts = contacts_mod.read_contacts()
    assert len(contacts) == 1, "a matched person must not create a duplicate contact"
    evidence = contacts_mod.read_evidence()
    assert any(e["field"] == "topic_discussed" and e["value"] == "Renewal timeline" and e["contact_id"] == "CONT-0001" for e in evidence)


def test_ingest_new_person_creates_provisional_contact_and_evidence(patched_contacts, tmp_path):
    payload = {
        "source_type": "transcript",
        "people": [{
            "name": "Brand New Person", "company": "Acme",
            "evidence": [{"field": "priority", "value": "Wants a joint roadmap review", "confidence": "confirmed"}],
        }],
    }
    path = _write_payload(tmp_path, payload)
    contacts_mod.cmd_ingest(SimpleNamespace(file=path, dry_run=False))

    contacts = contacts_mod.read_contacts()
    assert len(contacts) == 2
    new_row = next(r for r in contacts if r["canonical_name"] == "Brand New Person")
    assert new_row["status"] == "provisional"
    evidence = contacts_mod.read_evidence()
    assert any(e["field"] == "priority" and e["contact_id"] == new_row["contact_id"] for e in evidence)


def test_ingest_needs_review_person_gets_new_contact_plus_possible_duplicate_flag(patched_contacts, tmp_path):
    payload = {
        "source_type": "document",
        "people": [{"name": "Jamie Chung", "evidence": []}],
    }
    path = _write_payload(tmp_path, payload)
    contacts_mod.cmd_ingest(SimpleNamespace(file=path, dry_run=False))

    contacts = contacts_mod.read_contacts()
    assert len(contacts) == 2, "needs_review must create its own new contact, never silently merge into CONT-0001"
    new_row = next(r for r in contacts if r["contact_id"] != "CONT-0001")
    assert new_row["status"] == "provisional"

    evidence = contacts_mod.read_evidence()
    flag = next(e for e in evidence if e["field"] == "possible_duplicate" and e["contact_id"] == new_row["contact_id"])
    assert "CONT-0001" in flag["value"]
    assert not flag["superseded_by"]


def test_ingest_dry_run_writes_nothing(patched_contacts, tmp_path):
    contacts_before = contacts_mod.read_contacts()
    evidence_before = contacts_mod.read_evidence()

    payload = {
        "source_type": "manual_note",
        "people": [{"name": "Should Not Persist", "evidence": [{"field": "general_note", "value": "x", "confidence": "probable"}]}],
    }
    path = _write_payload(tmp_path, payload)
    contacts_mod.cmd_ingest(SimpleNamespace(file=path, dry_run=True))

    assert contacts_mod.read_contacts() == contacts_before
    assert contacts_mod.read_evidence() == evidence_before


def test_ingest_malformed_payload_is_rejected_all_or_nothing(patched_contacts, tmp_path):
    """Intentional-failure case: one bad fact anywhere in the payload must
    reject the WHOLE batch and write nothing, not partially apply it."""
    contacts_before = contacts_mod.read_contacts()
    evidence_before = contacts_mod.read_evidence()

    payload = {
        "source_type": "meeting_note",
        "people": [
            {"name": "Valid Person", "evidence": [{"field": "priority", "value": "ok", "confidence": "confirmed"}]},
            {"name": "Bad Evidence Person", "evidence": [{"field": "priority", "value": "ok", "confidence": "not_a_real_confidence"}]},
        ],
    }
    path = _write_payload(tmp_path, payload)
    contacts_mod.cmd_ingest(SimpleNamespace(file=path, dry_run=False))

    assert contacts_mod.read_contacts() == contacts_before, "nothing must be written when any part of the payload is invalid"
    assert contacts_mod.read_evidence() == evidence_before


def test_validate_ingest_payload_rejects_missing_source_type():
    errors = contacts_mod.validate_ingest_payload({"people": [{"name": "X"}]})
    assert any("source_type" in e for e in errors)


def test_validate_ingest_payload_rejects_empty_people():
    errors = contacts_mod.validate_ingest_payload({"source_type": "manual_note", "people": []})
    assert any("people" in e for e in errors)


def test_validate_ingest_payload_accepts_minimal_valid_payload():
    errors = contacts_mod.validate_ingest_payload({"source_type": "manual_note", "people": [{"name": "X"}]})
    assert errors == []


# ---------------------------------------------------------------------------
# Phase 2: possible_duplicate surfaced in compute_profile_summary
# ---------------------------------------------------------------------------

def test_compute_profile_summary_surfaces_unresolved_possible_duplicate(patched_contacts, tmp_path):
    payload = {"source_type": "document", "people": [{"name": "Jamie Chung", "evidence": []}]}
    path = _write_payload(tmp_path, payload)
    contacts_mod.cmd_ingest(SimpleNamespace(file=path, dry_run=False))

    contacts = contacts_mod.read_contacts()
    new_row = next(r for r in contacts if r["contact_id"] != "CONT-0001")
    evidence = contacts_mod.read_evidence()
    aliases = contacts_mod.read_aliases()

    summary = contacts_mod.compute_profile_summary(new_row["contact_id"], contacts, evidence, aliases)
    assert summary["possible_duplicates"], "unresolved possible_duplicate evidence must be surfaced"
    assert "CONT-0001" in summary["possible_duplicates"][0]
    assert "NEEDS REVIEW" in summary["text"]
    # Must appear near the top of the rendered text, not buried after
    # ordinary evidence sections.
    lines = summary["text"].split("\n")
    assert "NEEDS REVIEW" in lines[1]


def test_compute_profile_summary_possible_duplicate_excluded_from_probable_section(patched_contacts, tmp_path):
    """possible_duplicate is a system-generated review flag, not extracted
    content — it must not also leak into the ordinary probable/confirmed
    evidence lines."""
    payload = {"source_type": "document", "people": [{"name": "Jamie Chung", "evidence": []}]}
    path = _write_payload(tmp_path, payload)
    contacts_mod.cmd_ingest(SimpleNamespace(file=path, dry_run=False))

    contacts = contacts_mod.read_contacts()
    new_row = next(r for r in contacts if r["contact_id"] != "CONT-0001")
    evidence = contacts_mod.read_evidence()
    aliases = contacts_mod.read_aliases()
    summary = contacts_mod.compute_profile_summary(new_row["contact_id"], contacts, evidence, aliases)
    assert not any("Possibly the same person" in line for line in summary["probable"])
    assert not any("Possibly the same person" in line for line in summary["confirmed"])
