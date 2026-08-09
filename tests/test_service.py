from datetime import date, timedelta

import pytest

from jobos.domain import Stage
from jobos.service import JobOS
from jobos.store import ApplicationStore, ConcurrencyError


def _service(tmp_path) -> JobOS:
    return JobOS(ApplicationStore(tmp_path / "jobos.sqlite3"))


def test_application_lifecycle_records_an_audit_trail(tmp_path) -> None:
    service = _service(tmp_path)
    application = service.add_application(
        company="Northstar Labs",
        role="Systems Engineer",
        source="Referral",
        priority=5,
    )

    applied = service.move(
        application_id=application.id,
        target=Stage.APPLIED,
        expected_version=application.version,
        today=date(2026, 8, 9),
    )

    assert applied.stage is Stage.APPLIED
    assert applied.applied_on == date(2026, 8, 9)
    assert applied.version == 2
    events = service.store.events(application.id)
    assert [event.event_type for event in events] == ["created", "stage_changed"]
    assert events[-1].from_stage is Stage.SAVED
    assert events[-1].to_stage is Stage.APPLIED


def test_invalid_transition_is_rejected(tmp_path) -> None:
    service = _service(tmp_path)
    application = service.add_application(company="Northstar Labs", role="Systems Engineer")

    with pytest.raises(ValueError, match="cannot move"):
        service.move(
            application_id=application.id,
            target=Stage.OFFER,
            expected_version=application.version,
            today=date(2026, 8, 9),
        )


def test_stale_versions_protect_against_lost_updates(tmp_path) -> None:
    service = _service(tmp_path)
    application = service.add_application(company="Northstar Labs", role="Systems Engineer")
    service.plan_next_action(
        application_id=application.id,
        action="Research the team",
        due=date(2026, 8, 10),
        expected_version=application.version,
    )

    with pytest.raises(ConcurrencyError, match="refresh"):
        service.plan_next_action(
            application_id=application.id,
            action="Send note",
            due=date(2026, 8, 11),
            expected_version=application.version,
        )


def test_dashboard_surfaces_overdue_and_todays_actions(tmp_path) -> None:
    service = _service(tmp_path)
    today = date(2026, 8, 9)
    overdue = service.add_application(company="Atlas", role="Researcher")
    due_today = service.add_application(company="Beacon", role="Engineer")
    completed = service.add_application(company="Comet", role="Designer")

    service.plan_next_action(
        application_id=overdue.id,
        action="Send a follow-up",
        due=today - timedelta(days=1),
        expected_version=overdue.version,
    )
    service.plan_next_action(
        application_id=due_today.id,
        action="Prepare for screen",
        due=today,
        expected_version=due_today.version,
    )
    withdrawn = service.move(
        application_id=completed.id,
        target=Stage.WITHDRAWN,
        expected_version=completed.version,
        today=today,
    )

    dashboard = service.dashboard(today=today)

    assert dashboard.active_count == 2
    assert [item.company for item in dashboard.overdue] == ["Atlas"]
    assert [item.company for item in dashboard.due_today] == ["Beacon"]
    with pytest.raises(ValueError, match="terminal applications"):
        service.plan_next_action(
            application_id=withdrawn.id,
            action="Do not schedule",
            due=today,
            expected_version=withdrawn.version,
        )
