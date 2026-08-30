"""Issue 23 metered plan tests. All provider behavior is fake and offline."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil

import pytest

from app.domain.ledger import BudgetExceededError, CreditLedger, UsageRecord
from app.domain.provenance import AcquisitionRecord
from app.integrations.fortyguard.client import ActivityMetadata, ActivityRecoveryMetadata
from app.services.issue23_acquisition import (
    DEFAULT_OUT_DIR,
    canonical_resume_activities,
    execute_issue23_canonical_resume,
    execute_issue23_hotels_resume,
    execute_issue23_plan,
    hotel_resume_activities,
    issue23_activities,
    planned_issue23_env_recovery,
    planned_issue23_hotels_resume,
    planned_canonical_resume_requests,
    planned_requests,
    recover_issue23_canonical_env,
)
from app.services.sidecars import sidecar_path

SUBMITTED_AT = datetime(2026, 8, 30, 12, tzinfo=timezone.utc)


def _feature(value: float) -> dict[str, object]:
    return {
        "type": "Feature",
        "geometry": {
            "type": "Polygon",
            "coordinates": [
                [
                    [-98.50, 29.42],
                    [-98.49, 29.42],
                    [-98.49, 29.43],
                    [-98.50, 29.43],
                    [-98.50, 29.42],
                ]
            ],
        },
        "properties": {"id": "tile", "average_temperature": value, "value": value},
    }


class FakeClient:
    def __init__(self, *, weak_temperature: float = 36.5) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []
        self.weak_temperature = weak_temperature

    def submit_and_poll(
        self, endpoint: str, payload: dict[str, object], **kwargs: object
    ) -> tuple[dict[str, object], ActivityMetadata]:
        del kwargs
        self.calls.append((endpoint, payload))
        activity_id = f"issue23-{len(self.calls)}"
        metadata = ActivityMetadata(activity_id, SUBMITTED_AT, endpoint, tuple(payload))
        if endpoint == "/v1/env_params":
            date_time = payload["date_time"]
            assert isinstance(date_time, dict)
            start = int(str(date_time["start_time"])[:2])
            end = int(str(date_time["end_time"])[:2])
            timestamps = [f"2024-07-15T{hour:02d}:00:00-05:00" for hour in range(start, end + 1)]
            return {
                "timestamps": timestamps,
                "timezone": "America/Chicago",
                "heat_index_celsius": [36.0] * len(timestamps),
                "relative_humidity_percent": [50.0] * len(timestamps),
            }, metadata
        analytic = payload["analytic_type"]
        value = 2.0 if analytic != "tcm" else 37.5
        if len(self.calls) == 3:
            value = self.weak_temperature
        return {"map_data": {"type": "FeatureCollection", "features": [_feature(value)]}}, metadata


class FakeRecoveryClient:
    def __init__(self) -> None:
        self.gets: list[str] = []

    def poll_existing_activity(
        self, activity_id: str, **kwargs: object
    ) -> tuple[dict[str, object], ActivityRecoveryMetadata]:
        del kwargs
        self.gets.append(activity_id)
        timestamps = [f"2024-07-15T{hour:02d}:00:00-07:00" for hour in range(8, 20)]
        return {
            "timestamps": timestamps,
            "timezone": "GMT-7",
            "heat_index_celsius": [36.0] * len(timestamps),
            "relative_humidity_percent": [50.0] * len(timestamps),
            "api_key": "must-not-be-written",
        }, ActivityRecoveryMetadata(activity_id, SUBMITTED_AT)


def _copy_canonical_prerequisite(out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    source = DEFAULT_OUT_DIR / issue23_activities()[0].filename
    target = out_dir / source.name
    shutil.copy2(source, target)
    shutil.copy2(sidecar_path(source), sidecar_path(target))
    return target


def test_plan_is_exact_ordered_secret_free_and_does_not_call(tmp_path: Path) -> None:
    plan = planned_requests(tmp_path)
    assert [item["order"] for item in plan] == list(range(1, 10))
    assert [item["name"] for item in plan] == [activity.name for activity in issue23_activities()]
    assert [item["action"] for item in plan] == ["submit"] * 9
    assert [item["endpoint"] for item in plan] == ["/v1/heatmap"] * 3 + ["/v1/env_params"] * 3 + [
        "/v1/heatmap"
    ] * 3
    rendered = json.dumps(plan).lower()
    assert "api_key" not in rendered
    assert "authorization" not in rendered


def test_fresh_execution_submits_exact_nine_ordered_requests(tmp_path: Path) -> None:
    client = FakeClient()
    outcomes = execute_issue23_plan(client, CreditLedger(budget=9), out_dir=tmp_path)
    assert len(outcomes) == 9
    assert [endpoint for endpoint, _ in client.calls] == ["/v1/heatmap"] * 3 + [
        "/v1/env_params"
    ] * 3 + ["/v1/heatmap"] * 3
    date_times = [payload["date_time"] for _, payload in client.calls]
    assert date_times[:6] == [
        {"start_date": "2024-07-15", "filter_type": 2, "start_time": "08:00", "end_time": "19:00"},
        {"start_date": "2024-07-15", "filter_type": 2, "start_time": "10:00", "end_time": "16:00"},
        {"start_date": "2024-07-15", "filter_type": 2, "start_time": "10:00", "end_time": "16:00"},
        {"start_date": "2024-07-15", "filter_type": 2, "start_time": "08:00", "end_time": "19:00"},
        {"start_date": "2024-07-15", "filter_type": 2, "start_time": "10:00", "end_time": "16:00"},
        {"start_date": "2024-07-15", "filter_type": 2, "start_time": "10:00", "end_time": "16:00"},
    ]
    assert [payload.get("temperature") for _, payload in client.calls[3:6]] == [37.5, 37.5, 36.5]


def test_env_sidecar_records_derived_anchor_and_provider_identity(tmp_path: Path) -> None:
    execute_issue23_plan(FakeClient(), CreditLedger(budget=9), out_dir=tmp_path)
    sidecar = tmp_path / "menger-alamo-destination-env-params-2024-07-15.acquisition.json"
    record = AcquisitionRecord.from_payload(json.loads(sidecar.read_text(encoding="utf-8")))
    assert (record.source, record.provider, record.endpoint) == (
        "provider",
        "fortyguard",
        "/v1/env_params",
    )
    assert record.request_configuration["anchor_celsius"] == 37.5
    assert (
        record.request_configuration["anchor_derivation"] == "max_normalized_tcm_in_requested_range"
    )
    assert record.derived_from[0].role == "temperature_anchor_tcm"
    assert record.transformations[-1].name == "max_normalized_tcm_in_requested_range"


def test_hotel_metadata_truthfully_reuses_date_tcm_for_declared_windows(tmp_path: Path) -> None:
    outcomes = execute_issue23_plan(FakeClient(), CreditLedger(budget=9), out_dir=tmp_path)
    records = [outcome.record for outcome in outcomes[6:]]
    for record in records:
        config = record.request_configuration
        assert config["request_scope"] == "canonical_district_anchor"
        assert config["analysis_aoi"] == {
            "south": 29.421,
            "west": -98.49,
            "north": 29.429,
            "east": -98.482,
        }
        assert config["declared_windows"] == [
            {
                "label": "night",
                "start": "00:00",
                "end": "05:00",
                "timezone": "America/Chicago",
                "interval": "[start,end)",
            },
            {
                "label": "day",
                "start": "10:00",
                "end": "17:00",
                "timezone": "America/Chicago",
                "interval": "[start,end)",
            },
        ]
        assert config["timezone"] == "America/Chicago"
        assert config["temporal_basis"] == "date_level_tcm"
        assert config["provider_window_validated"] is False
        assert config["caveat_code"] == "date_level_not_interval_maximum"
        assert any(t.name == "point_to_aoi_expansion" for t in record.transformations)
    assert records[1].request_configuration["threshold_celsius"] == 35.0
    assert records[1].request_configuration["direction"] == "above"
    assert records[2].request_configuration["threshold_celsius"] == 35.0
    assert records[2].request_configuration["direction"] == "above"
    assert records[0].request_configuration["reused_for_components"] == ["night", "day"]


def test_preflight_rejects_overwrite_and_budget_before_calls(tmp_path: Path) -> None:
    target = tmp_path / issue23_activities()[-1].filename
    target.write_text("{}\n", encoding="utf-8")
    client = FakeClient()
    with pytest.raises(FileExistsError):
        execute_issue23_plan(client, CreditLedger(budget=9), out_dir=tmp_path)
    assert client.calls == []
    target.unlink()
    with pytest.raises(BudgetExceededError):
        execute_issue23_plan(client, CreditLedger(budget=8), out_dir=tmp_path)
    assert client.calls == []


def test_mild_weak_scenario_preserves_tcm_and_stops_dependents(tmp_path: Path) -> None:
    client = FakeClient(weak_temperature=34.9)
    with pytest.raises(ValueError, match="weak scenario gate not elevated"):
        execute_issue23_plan(client, CreditLedger(budget=9), out_dir=tmp_path)
    assert len(client.calls) == 3
    assert (tmp_path / "cathedral-governors-palace-destination-tcm-2024-07-15.json").is_file()
    assert not (tmp_path / "menger-alamo-destination-env-params-2024-07-15.json").exists()


def test_existing_valid_tcm_is_replayed_without_submission(tmp_path: Path) -> None:
    initial = FakeClient(weak_temperature=34.9)
    with pytest.raises(ValueError, match="weak scenario gate"):
        execute_issue23_plan(initial, CreditLedger(budget=9), out_dir=tmp_path)
    # The first run only needs to leave valid TCM prerequisites. Make the weak result mild above.
    weak_path = tmp_path / "cathedral-governors-palace-destination-tcm-2024-07-15.json"
    payload = json.loads(weak_path.read_text(encoding="utf-8"))
    payload["map_data"]["features"][0]["properties"]["average_temperature"] = 36.5
    payload["map_data"]["features"][0]["properties"]["value"] = 36.5
    weak_path.write_text(json.dumps(payload), encoding="utf-8")
    replay_client = FakeClient()
    outcomes = execute_issue23_plan(replay_client, CreditLedger(budget=6), out_dir=tmp_path)
    assert len(outcomes) == 6
    assert [endpoint for endpoint, _ in replay_client.calls] == ["/v1/env_params"] * 3 + [
        "/v1/heatmap"
    ] * 3


def test_superseded_canonical_resume_plan_is_rejected(tmp_path: Path) -> None:
    _copy_canonical_prerequisite(tmp_path)
    with pytest.raises(ValueError, match="superseded"):
        planned_canonical_resume_requests(tmp_path)


def test_superseded_canonical_resume_execute_fails_without_calls(
    tmp_path: Path,
) -> None:
    _copy_canonical_prerequisite(tmp_path)
    client = FakeClient()
    with pytest.raises(ValueError, match="superseded"):
        execute_issue23_canonical_resume(client, CreditLedger(budget=4), out_dir=tmp_path)
    assert client.calls == []


def test_superseded_canonical_resume_plan_mode_does_not_load_settings_or_client(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from scripts import acquire_fixture

    _copy_canonical_prerequisite(tmp_path)

    def fail() -> None:
        raise AssertionError("plan mode must not load live settings")

    monkeypatch.setattr(acquire_fixture, "load_settings", fail)
    monkeypatch.setattr(acquire_fixture, "build_live_client", fail)
    with pytest.raises(ValueError, match="superseded"):
        acquire_fixture.main(["--plan-issue-23-canonical-resume", "--out-dir", str(tmp_path)])
    assert capsys.readouterr().out == ""


def test_canonical_env_recovery_is_get_only_and_preserves_mismatch_metadata(
    tmp_path: Path,
) -> None:
    prerequisite = _copy_canonical_prerequisite(tmp_path)
    activity_id = "f579d84c-9c17-41d5-b42f-84f0e261e344"
    completed_at = datetime(2026, 8, 30, 14, 55, tzinfo=timezone.utc)
    ledger = CreditLedger(
        budget=1,
        initial_records=[
            UsageRecord(activity_id, "/v1/env_params", None, completed_at, "completed")
        ],
    )
    client = FakeRecoveryClient()
    before = ledger.call_count

    outcome = recover_issue23_canonical_env(client, ledger, activity_id, out_dir=tmp_path)

    assert client.gets == [activity_id]
    assert ledger.call_count == before
    assert outcome.record.activity_id == activity_id
    assert outcome.record.retrieved_at == completed_at
    assert outcome.record.status == "ok"
    config = outcome.record.request_configuration
    assert config["anchor_celsius"] == 34.0147
    assert config["anchor_derivation"] == "max_normalized_tcm_in_requested_range"
    assert config["observed_timezone"] == "GMT-7"
    assert config["expected_timezone"] == "America/Chicago"
    assert config["temporal_evidence"] == "inconsistent"
    assert config["caveat_code"] == "provider_timezone_mismatch"
    assert config["provider_date_and_hours_validated"] is True
    assert (
        outcome.record.derived_from[0].sha256
        == hashlib.sha256(prerequisite.read_bytes()).hexdigest()
    )
    assert outcome.record.transformations[-1].name == "max_normalized_tcm_in_requested_range"
    assert "must-not-be-written" not in outcome.fixture_path.read_text(encoding="utf-8")


@pytest.mark.parametrize("ledger_case", ["missing", "wrong_endpoint"])
def test_canonical_env_recovery_requires_matching_ledger_before_get(
    tmp_path: Path, ledger_case: str
) -> None:
    _copy_canonical_prerequisite(tmp_path)
    activity_id = "existing-activity"
    records = []
    if ledger_case == "wrong_endpoint":
        records.append(UsageRecord(activity_id, "/v1/heatmap", None, SUBMITTED_AT, "completed"))
    ledger = CreditLedger(initial_records=records)
    client = FakeRecoveryClient()

    with pytest.raises(ValueError, match="not present|not /v1/env_params"):
        recover_issue23_canonical_env(client, ledger, activity_id, out_dir=tmp_path)
    assert client.gets == []


def test_canonical_env_recovery_refuses_overwrite_before_get(tmp_path: Path) -> None:
    _copy_canonical_prerequisite(tmp_path)
    activity_id = "existing-activity"
    target = tmp_path / canonical_resume_activities()[1].filename
    sidecar_path(target).write_text("{}\n", encoding="utf-8")
    ledger = CreditLedger(
        initial_records=[
            UsageRecord(activity_id, "/v1/env_params", None, SUBMITTED_AT, "completed")
        ]
    )
    client = FakeRecoveryClient()

    with pytest.raises(FileExistsError, match="refusing to overwrite"):
        recover_issue23_canonical_env(client, ledger, activity_id, out_dir=tmp_path)
    assert client.gets == []


def test_hotel_only_resume_plans_and_submits_exactly_three(tmp_path: Path) -> None:
    plan = planned_issue23_hotels_resume(tmp_path)
    assert [item["name"] for item in plan] == [item.name for item in hotel_resume_activities()]
    assert [item["endpoint"] for item in plan] == ["/v1/heatmap"] * 3
    assert all(item["temporal_basis"] == "date_level_tcm" for item in plan)
    assert all(item["caveat_code"] == "date_level_not_interval_maximum" for item in plan)

    client = FakeClient()
    outcomes = execute_issue23_hotels_resume(client, CreditLedger(budget=3), out_dir=tmp_path)
    assert len(outcomes) == 3
    assert [endpoint for endpoint, _ in client.calls] == ["/v1/heatmap"] * 3
    assert [payload["analytic_type"] for _, payload in client.calls] == [
        "tcm",
        "exceedance",
        "persistence",
    ]


def test_hotel_only_resume_preflights_all_six_paths_and_three_slots(tmp_path: Path) -> None:
    target = tmp_path / hotel_resume_activities()[-1].filename
    sidecar_path(target).write_text("{}\n", encoding="utf-8")
    client = FakeClient()
    with pytest.raises(FileExistsError, match="refusing to overwrite"):
        execute_issue23_hotels_resume(client, CreditLedger(budget=3), out_dir=tmp_path)
    assert client.calls == []
    sidecar_path(target).unlink()
    with pytest.raises(BudgetExceededError, match="needs 3 calls"):
        execute_issue23_hotels_resume(client, CreditLedger(budget=2), out_dir=tmp_path)
    assert client.calls == []


def test_new_plan_modes_do_not_load_settings_or_construct_client(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from scripts import acquire_fixture

    _copy_canonical_prerequisite(tmp_path)

    def fail() -> None:
        raise AssertionError("plan mode must not load live settings or construct a client")

    monkeypatch.setattr(acquire_fixture, "load_settings", fail)
    monkeypatch.setattr(acquire_fixture, "build_live_client", fail)
    activity_id = "existing-activity"
    assert (
        acquire_fixture.main(
            [
                "--plan-issue-23-canonical-env-recovery",
                "--activity-id",
                activity_id,
                "--out-dir",
                str(tmp_path),
            ]
        )
        == 0
    )
    recovery = json.loads(capsys.readouterr().out)
    assert recovery["activity_id"] == activity_id
    assert "api_key" not in json.dumps(recovery).lower()
    assert acquire_fixture.main(["--plan-issue-23-hotels-resume", "--out-dir", str(tmp_path)]) == 0
    hotels = json.loads(capsys.readouterr().out)
    assert len(hotels) == 3


def test_env_recovery_plan_preflights_prerequisite_and_target(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="canonical TCM prerequisite"):
        planned_issue23_env_recovery("existing-activity", tmp_path)
