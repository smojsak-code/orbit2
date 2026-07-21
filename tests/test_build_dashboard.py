"""
scripts/build_dashboard.py's own pure-logic tests.

The full build pipeline (scoring -> node report generation -> LibreOffice
PDF conversion -> base64 embedding) is deliberately NOT exercised here — it
shells out to real subprocesses (node, soffice) and takes real wall-clock
time, so it's covered instead by scripts/validate_release.py's step_web_build
smoke test (see tests/test_validate_release.py for the pure, unit-testable
half of that check). What IS unit-tested here is the one piece of
build_objectives_report()'s own logic that doesn't require a real build:
its empty-input short-circuit, so a fresh install with no objectives.csv
rows doesn't attempt to shell out to node/soffice at all.
"""
import build_dashboard


def test_build_objectives_report_returns_none_for_no_objectives():
    """A fresh install (or a fixture set with an empty objectives.csv)
    must not attempt to invoke node/soffice at all — same "nothing to
    report on yet" short-circuit build_vendor_reports() doesn't need
    (vendors always exist from weights.json) but objectives.csv can
    legitimately start empty."""
    assert build_dashboard.build_objectives_report([]) is None
    assert build_dashboard.build_objectives_report(None) is None
