"""Reports must not export private data, including unexpected fields."""

import json
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

from custom_components.mashov.reporting import diagnostic_summary, issue_report_url


def test_release_versions_match():
    """VERSION, manifest.json and ``reporting.VERSION`` all carry the same release number."""
    from pathlib import Path

    from custom_components.mashov.reporting import VERSION

    root = Path(__file__).resolve().parents[1]
    assert root.joinpath("VERSION").read_text().strip() == VERSION
    assert json.loads(root.joinpath("custom_components/mashov/manifest.json").read_text())["version"] == VERSION


def test_diagnostics_allowlist_drops_private_values_and_dynamic_keys():
    """Diagnostics keep only allowlisted counts; private values and unknown keys/statuses are dropped."""
    secret = "PRIVATE-STUDENT-TOKEN-NOTE"
    coordinator = SimpleNamespace(
        last_update_success=False,
        data={
            "students": [{"id": secret, "name": secret}],
            "auth": {"token": secret},
            "by_slug": {
                secret: {
                    "grades": [secret],
                    "additional_data": {
                        "message_board": {"status": "ok", "items": [{"text": secret}]},
                        "student_files": {"status": secret},
                        secret: {"status": "ok"},
                    },
                }
            },
        },
    )
    result = diagnostic_summary(coordinator)
    assert secret not in json.dumps(result)
    assert result["student_count"] == 1
    assert result["optional_resource_status_counts"] == {
        "message_board": {"ok": 1},
        "student_files": {"other_error": 1},
    }


def test_report_prefills_existing_form_without_raw_exception():
    """The report URL prefills the GitHub bug form with a mapped event name, never the raw title."""
    url = issue_report_url("Mashov refresh failed")
    assert urlparse(url).netloc == "github.com"
    params = parse_qs(urlparse(url).query)
    assert params["template"] == ["bug_report.yml"]
    assert json.loads(params["debug_logs"][0])["event"] == "refresh_failed"
    assert "PRIVATE" not in issue_report_url("PRIVATE")
