"""The synthetic triage-fixture harness, and the honesty of what it claims."""

import json
import subprocess
import sys

from runsense.perception_eval import STATUS, evaluate_perception, fixtures, run_fixture

REPORT = evaluate_perception()


def test_every_fixture_passes():
    failed = [result["name"] for result in REPORT["results"] if not result["passed"]]
    assert failed == [], REPORT
    assert REPORT["fixtures_passed"] == REPORT["fixtures_total"] == len(fixtures())


def test_report_shape():
    assert set(REPORT) == {"status", "detail", "fixtures_passed", "fixtures_total", "evidence",
                           "unmeasured", "results"}
    assert REPORT["fixtures_total"] >= 8
    assert REPORT["evidence"] == "synthetic_detection_sequences"
    for result in REPORT["results"]:
        assert set(result) == {"name", "plan_rule", "passed", "frames", "expected", "observed",
                               "detail"}
        assert result["plan_rule"] and result["detail"]


def test_status_does_not_claim_a_computer_vision_measurement():
    assert REPORT["status"] == STATUS == "triage_logic_tested"
    # Nothing in the status may read as measured real-world perception.
    assert not any(word in REPORT["status"] for word in ("measured", "passed", "accurate",
                                                         "recall", "latency", "verified"))


def test_detail_names_what_stays_unmeasured():
    detail = REPORT["detail"].lower()
    assert "synthetic" in detail
    assert "unmeasured" in detail
    for claim in ("recall", "false-alert", "latency", "no camera"):
        assert claim in detail, claim
    assert any("latency" in item for item in REPORT["unmeasured"])
    assert any("recall" in item for item in REPORT["unmeasured"])


def test_fixtures_cover_every_row_of_the_plans_trigger_table():
    rules = " ".join(fixture.plan_rule for fixture in fixtures()).lower()
    for tier in ("danger", "warning", "notice", "silent"):
        assert tier in rules
    assert "debounce" in rules and "hysteresis" in rules and "pre-empts" in rules


def test_a_broken_expectation_is_reported_as_a_failure():
    # The harness must be able to fail: an impossible expectation must not pass.
    from dataclasses import replace

    broken = replace(fixtures()[0], expected=[(0, "notice", "nonsense")])
    assert run_fixture(broken)["passed"] is False


def test_runs_standalone_and_prints_the_report():
    completed = subprocess.run([sys.executable, "-m", "runsense.perception_eval"],
                               capture_output=True, text=True, check=False)
    assert completed.returncode == 0, completed.stderr
    printed = json.loads(completed.stdout)
    assert printed["status"] == STATUS
    assert printed["fixtures_passed"] == printed["fixtures_total"]


def test_evaluation_report_carries_the_real_perception_result():
    import asyncio

    from runsense.evaluation import evaluate

    report = asyncio.run(evaluate())
    # Perception stays a sibling key: it must not inflate the scenario tally.
    assert report["total"] == 16
    assert report["perception"]["status"] == STATUS
    assert report["perception"]["fixtures_total"] == REPORT["fixtures_total"]
