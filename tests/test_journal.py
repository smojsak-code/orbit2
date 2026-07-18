"""
Partner Value Journal CRUD tests (R1-T09 instruction #53).

Drives scripts/journal.py's actual cmd_create/cmd_edit/cmd_archive/cmd_list
functions (not reimplementations of their logic) against the isolated
fixture journal, using a lightweight argparse.Namespace-compatible object
for `args` — the same shape the real CLI parser builds.
"""
from types import SimpleNamespace


def journal_create_args(**overrides):
    defaults = dict(
        date="2026-07-10", type="qbr", title="Test-created fixture activity",
        description="", participants=None, organisation="Fixture Corp",
        customer_account="", contribution_type="led", outcome="Fixture outcome.",
        next_action="", metric_links=None, opportunity_links=None, evidence_links=None,
        value_amount=None, value_currency=None, value_status=None,
        recognition_status=None, visibility="communardo_internal",
        source_type=None, confidence=None, notes=None,
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def test_create_adds_a_new_entry_with_sequential_id(patched_journal, capsys):
    before = patched_journal.read_journal()
    before_count = len(before)

    patched_journal.cmd_create(journal_create_args())

    after = patched_journal.read_journal()
    assert len(after) == before_count + 1
    new_entry = after[-1]
    assert new_entry["activity_id"] == "ACT-0004"  # fixture already has ACT-0001..0003
    assert new_entry["title"] == "Test-created fixture activity"
    assert new_entry["status"] == "active"
    assert new_entry["outcome"] == "Fixture outcome."


def test_edit_updates_only_requested_fields(patched_journal):
    original = {e["activity_id"]: dict(e) for e in patched_journal.read_journal()}["ACT-0001"]

    edit_args = SimpleNamespace(
        activity_id="ACT-0001", date=None, type=None, title="Updated fixture title",
        description=None, organisation=None, customer_account=None, contribution_type=None,
        outcome=None, next_action=None, recognition_status=None, visibility=None,
        source_type=None, confidence=None, notes=None,
        participants=None, metric_links=None, opportunity_links=None, evidence_links=None,
        value_amount=None, value_currency=None, value_status=None,
    )
    patched_journal.cmd_edit(edit_args)

    updated = {e["activity_id"]: e for e in patched_journal.read_journal()}["ACT-0001"]
    assert updated["title"] == "Updated fixture title"
    # Untouched fields must survive unchanged.
    assert updated["outcome"] == original["outcome"]
    assert updated["organisation"] == original["organisation"]
    assert updated["updated_at"] != original["updated_at"]


def test_archive_never_deletes_the_row(patched_journal):
    before_count = len(patched_journal.read_journal())

    archive_args = SimpleNamespace(activity_id="ACT-0002", reason="Fixture archive reason")
    patched_journal.cmd_archive(archive_args)

    after = patched_journal.read_journal()
    assert len(after) == before_count, "archiving must not remove the row"
    archived = {e["activity_id"]: e for e in after}["ACT-0002"]
    assert archived["status"] == "archived"
    assert archived["archived_reason"] == "Fixture archive reason"
    assert archived["archived_at"] is not None


def test_archive_twice_is_a_safe_no_op(patched_journal, capsys):
    archive_args = SimpleNamespace(activity_id="ACT-0002", reason="First reason")
    patched_journal.cmd_archive(archive_args)
    first_archived_at = {e["activity_id"]: e for e in patched_journal.read_journal()}["ACT-0002"]["archived_at"]

    patched_journal.cmd_archive(SimpleNamespace(activity_id="ACT-0002", reason="Second reason"))
    second_archived_at = {e["activity_id"]: e for e in patched_journal.read_journal()}["ACT-0002"]["archived_at"]

    assert first_archived_at == second_archived_at, "re-archiving an already-archived entry must not change its timestamp"


def test_build_entry_from_fields_requires_title_and_outcome(patched_journal):
    entries = patched_journal.read_journal()
    with __import__("pytest").raises(KeyError):
        patched_journal._build_entry_from_fields({"date": "2026-07-01"}, entries)


def test_check_no_executable_content_flags_script_tags(patched_journal):
    """Intentional-failure case: a field containing a <script> tag must be
    flagged — proves the import-request injection guard (R1-T04) actually
    fires rather than always passing content through."""
    problems = patched_journal._check_no_executable_content({
        "title": "Looks fine", "outcome": "<script>alert(1)</script>",
    })
    assert problems == ["outcome"]


def test_check_no_executable_content_allows_plain_text(patched_journal):
    problems = patched_journal._check_no_executable_content({
        "title": "QBR notes", "outcome": "Discussed roadmap and next steps.",
    })
    assert problems == []
