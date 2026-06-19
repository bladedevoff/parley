"""Tests that code_scan and train_in_place do REAL computation (no stub formulas)."""

from __future__ import annotations

from pathlib import Path

from parley.ml import train_logreg
from parley.scanners import scan_repo, scan_text

REPO = Path(__file__).resolve().parent.parent / "examples" / "private_repo"


def test_scanner_finds_planted_secrets_and_injection():
    findings = scan_text("AWS_KEY = 'AKIA1234567890ABCDEF'\nrun = eval(x)\n")
    rules = {f["rule"] for f in findings}
    assert "secret:aws_access_key_id" in rules
    assert "injection:eval_exec" in rules


def test_scan_repo_returns_locations_not_source():
    res = scan_repo(REPO)
    assert res["files_scanned"] >= 1
    assert res["total_findings"] >= 4
    assert res["source_exported"] is False
    # locations are file:line:rule, never raw source text
    assert all(loc.count(":") >= 2 for loc in res["locations"])
    blob = " ".join(res["locations"])
    assert "AKIA" not in blob and "BEGIN" not in blob  # no secret VALUES leak


def test_scan_severity_rollup_is_real():
    res = scan_repo(REPO)
    by = res["findings_by_severity"]
    assert by.get("critical", 0) >= 1  # the planted AWS key / private key class
    assert sum(by.values()) == res["total_findings"]


def test_logreg_actually_trains_and_reports_held_out_accuracy():
    cohorts = {"a": 120, "b": 80, "c": 200, "d": 60}
    m = train_logreg(cohorts, seed="t")
    assert m["trained_on"] > 0 and m["validated_on"] > 0
    assert 0.0 <= m["val_accuracy"] <= 1.0
    assert m["rows_exported"] == 0
    # deterministic: same inputs -> same accuracy
    assert train_logreg(cohorts, seed="t")["val_accuracy"] == m["val_accuracy"]


def test_logreg_learns_signal_better_than_chance():
    # label is a deterministic function of the cohort, so the model should beat 0.5
    cohorts = {f"c{i}": 50 + i for i in range(8)}
    assert train_logreg(cohorts, seed="x")["val_accuracy"] >= 0.6
