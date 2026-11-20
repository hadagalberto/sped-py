from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from sped.core.validation import validate
from sped.factories.synthetic import SyntheticOptions, write_synthetic


def test_valid_file_has_no_issues(efd_file: Path) -> None:
    assert validate(efd_file) == []


def test_missing_required_records(tmp_path: Path) -> None:
    path = tmp_path / "empty.txt"
    path.write_bytes(b"")
    issues = validate(path)
    rules = {issue.rule for issue in issues}
    assert "SPED-STRUCT" in rules


def test_wrong_totals_detected(broken_file_factory: Callable[[str], Path]) -> None:
    issues = validate(broken_file_factory("wrong_file_total"))
    assert any(issue.rule == "SPED-9999" for issue in issues)


def test_missing_block_closing_detected(broken_file_factory: Callable[[str], Path]) -> None:
    issues = validate(broken_file_factory("missing_block_closing"))
    assert any(issue.code == "C990" for issue in issues)


def test_field_error_detected(broken_file_factory: Callable[[str], Path]) -> None:
    issues = validate(broken_file_factory("invalid_date"))
    assert any(issue.rule == "SPED-FIELD" for issue in issues)


def test_issue_as_dict(broken_file_factory: Callable[[str], Path]) -> None:
    issue = validate(broken_file_factory("wrong_file_total"))[0]
    assert set(issue.as_dict()) == {"rule", "line", "register", "message", "severity"}
    assert issue.as_dict()["severity"] == "error"


def test_out_of_order_file(tmp_path: Path) -> None:
    path = tmp_path / "order.txt"
    path.write_bytes(b"|0001|0|\n|9999|2|\n")
    issues = validate(path)
    assert any("começar com 0000" in issue.message for issue in issues)


def test_all_cod_versions_validate(tmp_path: Path) -> None:
    for cod in ("013", "014", "015", "016", "017", "018", "019", "020", "021"):
        path = write_synthetic(tmp_path / f"{cod}.txt", SyntheticOptions(cod_ver=cod))
        assert validate(path) == [], cod
