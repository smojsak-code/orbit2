"""
HTML structural checks (R1-T09 instruction #56): no duplicate element IDs,
every VIEWS entry has a matching #view*/#tab* pair. Runs against the real
dashboard.html and web/index_template.html — read-only (BeautifulSoup only
parses; nothing here ever writes to these files), so this does not conflict
with "tests do not modify production data" despite touching the real repo
files on disk.
"""
import os

import check_html

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_dashboard_html_has_no_duplicate_ids():
    result = check_html.check_file(os.path.join(BASE_DIR, "dashboard.html"))
    assert result["duplicate_ids"] == {}, result["duplicate_ids"]


def test_dashboard_html_nav_targets_all_present():
    result = check_html.check_file(os.path.join(BASE_DIR, "dashboard.html"))
    assert result["missing_nav_targets"] == []


def test_web_template_has_no_duplicate_ids():
    result = check_html.check_file(os.path.join(BASE_DIR, "web", "index_template.html"))
    assert result["duplicate_ids"] == {}, result["duplicate_ids"]


def test_web_template_nav_targets_all_present():
    result = check_html.check_file(os.path.join(BASE_DIR, "web", "index_template.html"))
    assert result["missing_nav_targets"] == []


def test_intentional_failure_duplicate_id_is_detected(tmp_path):
    """Intentional-failure case: two elements sharing an id must be
    reported — proves the duplicate-ID check actually fires."""
    html = """
    <html><body>
      <div id="viewHome"></div>
      <div id="viewHome"></div>
    </body></html>
    """
    p = tmp_path / "broken.html"
    p.write_text(html)
    result = check_html.check_file(str(p))
    assert result["duplicate_ids"] == {"viewHome": 2}


def test_intentional_failure_missing_nav_target_is_detected(tmp_path):
    """Intentional-failure case: a VIEWS entry with no matching element
    must be reported — proves the nav-target check actually fires."""
    html = """
    <html><body>
      <div id="viewHome"></div>
      <button id="tabHome"></button>
      <script>const VIEWS = ['home', 'phantom'];</script>
    </body></html>
    """
    p = tmp_path / "broken.html"
    p.write_text(html)
    result = check_html.check_file(str(p))
    assert any("phantom" in problem and "viewPhantom" in problem for problem in result["missing_nav_targets"])
    assert any("phantom" in problem and "tabPhantom" in problem for problem in result["missing_nav_targets"])


def test_file_with_no_views_array_is_trivially_clean(tmp_path):
    html = "<html><body><div id=\"a\"></div></body></html>"
    p = tmp_path / "plain.html"
    p.write_text(html)
    result = check_html.check_file(str(p))
    assert result == {"duplicate_ids": {}, "missing_nav_targets": []}
