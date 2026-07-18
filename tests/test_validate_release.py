"""
scripts/validate_release.py's own logic tests (R1-T09).

check_report_files_exist() is deliberately separated from step_web_build()
(which shells out to a real build) so its file-naming/existence logic can
be unit-tested against a throwaway tmp reports/ directory — no real build
or real reports/ directory involved.
"""
import os

import validate_release


def _touch(path, size=10):
    with open(path, "wb") as f:
        f.write(b"x" * size)


def test_report_files_exist_happy_path(tmp_path):
    reports_dir = str(tmp_path)
    _touch(os.path.join(reports_dir, "Orbit2_Report_TestVendor_2026-Q3.docx"))
    _touch(os.path.join(reports_dir, "Orbit2_Deck_TestVendor_2026-Q3.pptx"))

    ok, detail = validate_release.check_report_files_exist(reports_dir, ["TestVendor"])
    assert ok is True, detail


def test_report_files_intentional_failure_missing_pptx(tmp_path):
    """Intentional-failure case: a vendor with a Word report but no
    PowerPoint deck must be flagged — this is the exact bug the naming
    convention mismatch (Orbit2_Report_ vs Orbit2_Deck_) produced during
    R1-T09's own development, so this test locks in the fix."""
    reports_dir = str(tmp_path)
    _touch(os.path.join(reports_dir, "Orbit2_Report_TestVendor_2026-Q3.docx"))
    # No .pptx file created.

    ok, detail = validate_release.check_report_files_exist(reports_dir, ["TestVendor"])
    assert ok is False
    assert "pptx" in detail.lower()


def test_report_files_intentional_failure_empty_docx(tmp_path):
    """Intentional-failure case: a zero-byte report file (e.g. a generator
    that crashed after creating the file but before writing content) must
    be flagged as a failure, not just "file exists"."""
    reports_dir = str(tmp_path)
    _touch(os.path.join(reports_dir, "Orbit2_Report_TestVendor_2026-Q3.docx"), size=0)
    _touch(os.path.join(reports_dir, "Orbit2_Deck_TestVendor_2026-Q3.pptx"))

    ok, detail = validate_release.check_report_files_exist(reports_dir, ["TestVendor"])
    assert ok is False
    assert "empty" in detail.lower()


def test_report_files_intentional_failure_no_vendors_configured(tmp_path):
    ok, detail = validate_release.check_report_files_exist(str(tmp_path), [])
    assert ok is False
    assert "no vendors" in detail.lower()


def test_report_files_picks_the_most_recently_named_file_when_multiple_exist(tmp_path):
    """Two quarters of reports can coexist on disk (e.g. Q2 and Q3) —
    confirm the check doesn't just grab whichever sorts first and instead
    considers the latest, matching build_dashboard.py's own
    docx_candidates.sort() -> [-1] behaviour."""
    reports_dir = str(tmp_path)
    _touch(os.path.join(reports_dir, "Orbit2_Report_TestVendor_2026-Q2.docx"), size=0)  # older, empty
    _touch(os.path.join(reports_dir, "Orbit2_Report_TestVendor_2026-Q3.docx"), size=10)  # newer, populated
    _touch(os.path.join(reports_dir, "Orbit2_Deck_TestVendor_2026-Q3.pptx"), size=10)

    ok, detail = validate_release.check_report_files_exist(reports_dir, ["TestVendor"])
    assert ok is True, detail


def test_run_step_catches_an_exception_as_a_failure_not_a_crash():
    def _boom():
        raise RuntimeError("fixture failure")

    step = validate_release.run_step("fixture step", _boom)
    assert step.ok is False
    assert "fixture failure" in step.detail
