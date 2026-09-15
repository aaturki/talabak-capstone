"""Synthetic arithmetic fixtures only; these are not capstone benchmark results."""
from copy import deepcopy

import pytest

from scripts.breakeven import compute_breakeven


def synthetic_input():
    # 'live' exercises admissibility logic. These values are invented unit-test
    # fixtures, never exported as measurements or presented as project results.
    traffic = "a" * 64
    return {"schema_version": "breakeven-v1", "self_host_measurement": {
        "evidence_mode": "live", "measurement_kind": "self_hosted_load", "traffic_sha256": traffic,
        "source_artifact_sha256": "b" * 64, "hardware": "SYNTHETIC TEST HARDWARE",
        "model_id": "SYNTHETIC TEST MODEL", "measured_at": "2026-09-15T12:00:00Z",
        "concurrency": 4, "batch_size": 2, "saturation_observed": False,
        "totals": {"completed_requests": 100, "attempted_requests": 100, "elapsed_seconds": 10}},
        "assumptions": {"monthly_fixed_usd": 100, "variable_usd_per_request": .01,
                        "available_hours_per_month": 1, "planned_utilization": .5,
                        "basis": "SYNTHETIC TEST ASSUMPTIONS ONLY"},
        "routes": {name: {"evidence_mode": "live", "traffic_sha256": traffic,
                           "source_artifact_sha256": "c" * 64, "model_id": "SYNTHETIC ROUTE",
                           "measured_requests": 100, "cost_usd_per_request": price,
                           "cost_basis": "SYNTHETIC UNIT-TEST VALUE"}
                   for name, price in (("commercial", .03), ("open_weight_gateway", .005))}}


def test_no_measurements_stays_not_measured_without_numbers():
    report = compute_breakeven()
    assert report["status"] == "NOT_MEASURED"
    assert "comparisons" not in report and "projected_capacity_requests_per_month" not in report


def test_both_routes_capacity_unit_cost_and_whole_request_crossing():
    report = compute_breakeven(synthetic_input())
    assert report["projected_capacity_requests_per_month"] == 36000
    assert report["planned_requests_per_month"] == 18000
    commercial = report["comparisons"]["commercial"]
    assert commercial["break_even_requests"] == pytest.approx(5000)
    assert commercial["minimum_whole_requests_for_parity"] == 5000
    assert commercial["minimum_whole_requests_for_strict_saving"] == 5001
    assert commercial["selfhost_unit_cost_at_planned_volume_usd"] == pytest.approx(280 / 18000)
    assert commercial["monthly_saving_at_planned_volume_usd"] == pytest.approx(260)
    assert report["comparisons"]["open_weight_gateway"]["status"] == "NO_COST_CROSSING"


def test_overlapping_intervals_do_not_double_count_concurrent_time():
    data = synthetic_input()
    measurement = data["self_host_measurement"]
    del measurement["totals"]
    measurement["windows"] = [
        {"started_at": "2026-09-15T12:00:00Z", "ended_at": "2026-09-15T12:00:30Z",
         "completed_requests": 300, "attempted_requests": 300},
        {"started_at": "2026-09-15T12:00:30Z", "ended_at": "2026-09-15T12:01:00Z",
         "completed_requests": 600, "attempted_requests": 600}]
    report = compute_breakeven(data)
    assert report["self_host_measurement"]["completed_requests_per_second"] == 15
    measurement["windows"][1]["started_at"] = "2026-09-15T12:00:20Z"
    with pytest.raises(ValueError, match="non-overlapping"):
        compute_breakeven(data)


def test_simulator_throughput_or_simulator_cost_is_rejected():
    data = synthetic_input()
    data["self_host_measurement"]["evidence_mode"] = "simulator"
    with pytest.raises(ValueError, match="live self-hosted"):
        compute_breakeven(data)
    data = synthetic_input()
    data["routes"]["commercial"]["evidence_mode"] = "simulator"
    with pytest.raises(ValueError, match="live cost"):
        compute_breakeven(data)


def test_different_traffic_is_not_a_comparable_cost_benchmark():
    data = synthetic_input()
    data["routes"]["open_weight_gateway"]["traffic_sha256"] = "d" * 64
    with pytest.raises(ValueError, match="same traffic"):
        compute_breakeven(data)


def test_equality_zero_utilization_and_unreachable_capacity_edges():
    data = synthetic_input()
    data["assumptions"]["monthly_fixed_usd"] = 0
    data["assumptions"]["planned_utilization"] = 0
    data["routes"]["commercial"]["cost_usd_per_request"] = .01
    report = compute_breakeven(data)
    assert report["comparisons"]["commercial"]["status"] == "ALWAYS_EQUAL"
    assert report["comparisons"]["commercial"]["selfhost_unit_cost_at_planned_volume_usd"] is None
    data = synthetic_input()
    data["assumptions"]["monthly_fixed_usd"] = 100000
    report = compute_breakeven(data)
    assert not report["comparisons"]["commercial"]["parity_feasible_within_measured_capacity"]


@pytest.mark.parametrize("key,value", [("elapsed_seconds", 0), ("elapsed_seconds", float("nan")),
                                      ("completed_requests", 101), ("completed_requests", 0),
                                      ("completed_requests", True)])
def test_invalid_measured_totals_are_rejected(key, value):
    data = synthetic_input()
    data["self_host_measurement"]["totals"][key] = value
    with pytest.raises(ValueError):
        compute_breakeven(data)
