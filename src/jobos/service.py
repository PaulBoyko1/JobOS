"""Application use cases and the prioritised daily dashboard."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from jobos.domain import (
    TERMINAL_STAGES,
    Application,
    Stage,
    clean_optional,
    clean_required,
    validate_priority,
    validate_transition,
)
from jobos.store import ApplicationStore


@dataclass(frozen=True)
class Dashboard:
    active_count: int
    overdue: tuple[Application, ...]
    due_today: tuple[Application, ...]
    offers: tuple[Application, ...]
    next_actions: tuple[Application, ...]


class JobOS:
    """Coordinates validated domain actions against one local application database."""

    def __init__(self, store: ApplicationStore) -> None:
        self.store = store
        self.store.initialize()

    def add_application(
        self,
        *,
        company: str,
        role: str,
        source: str | None = None,
        priority: int = 3,
        notes: str = "",
    ) -> Application:
        return self.store.create(
            company=clean_required(company, field="company"),
            role=clean_required(role, field="role"),
            source=clean_optional(source),
            priority=validate_priority(priority),
            notes=notes.strip(),
        )

    def move(
        self,
        *,
        application_id: int,
        target: Stage,
        expected_version: int,
        today: date,
    ) -> Application:
        application = self._get_required(application_id)
        validate_transition(application.stage, target)
        applied_on = application.applied_on
        if target is Stage.APPLIED and applied_on is None:
            applied_on = today
        return self.store.transition(
            application_id=application_id,
            target=target,
            expected_version=expected_version,
            applied_on=applied_on,
        )

    def plan_next_action(
        self,
        *,
        application_id: int,
        action: str | None,
        due: date | None,
        expected_version: int,
    ) -> Application:
        application = self._get_required(application_id)
        if application.stage in TERMINAL_STAGES and action is not None:
            raise ValueError("terminal applications cannot have a next action")
        cleaned_action = clean_optional(action)
        if cleaned_action is None and due is not None:
            raise ValueError("a due date requires a next action")
        return self.store.set_next_action(
            application_id=application_id,
            action=cleaned_action,
            due=due,
            expected_version=expected_version,
        )

    def applications(self, *, stage: Stage | None = None) -> list[Application]:
        return self.store.list(stage=stage)

    def dashboard(self, *, today: date) -> Dashboard:
        applications = self.store.list()
        active = tuple(
            application for application in applications if application.stage not in TERMINAL_STAGES
        )
        overdue = tuple(
            application
            for application in active
            if application.next_action_due is not None and application.next_action_due < today
        )
        due_today = tuple(
            application
            for application in active
            if application.next_action_due is not None and application.next_action_due == today
        )
        offers = tuple(
            application for application in active if application.stage is Stage.OFFER
        )
        next_actions = tuple(
            application for application in active if application.next_action is not None
        )
        return Dashboard(
            active_count=len(active),
            overdue=overdue,
            due_today=due_today,
            offers=offers,
            next_actions=next_actions,
        )

    def _get_required(self, application_id: int) -> Application:
        application = self.store.get(application_id)
        if application is None:
            raise KeyError(f"application {application_id} does not exist")
        return application
