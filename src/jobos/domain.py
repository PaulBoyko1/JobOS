"""Core workflow rules for a deliberate, local-first job search."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from typing import Final


class Stage(StrEnum):
    SAVED = "saved"
    APPLIED = "applied"
    SCREEN = "screen"
    INTERVIEW = "interview"
    OFFER = "offer"
    ACCEPTED = "accepted"
    DECLINED = "declined"
    REJECTED = "rejected"
    WITHDRAWN = "withdrawn"


TERMINAL_STAGES: Final[frozenset[Stage]] = frozenset(
    {Stage.ACCEPTED, Stage.DECLINED, Stage.REJECTED, Stage.WITHDRAWN}
)
STAGE_TRANSITIONS: Final[dict[Stage, frozenset[Stage]]] = {
    Stage.SAVED: frozenset({Stage.APPLIED, Stage.WITHDRAWN}),
    Stage.APPLIED: frozenset({Stage.SCREEN, Stage.REJECTED, Stage.WITHDRAWN}),
    Stage.SCREEN: frozenset({Stage.INTERVIEW, Stage.REJECTED, Stage.WITHDRAWN}),
    Stage.INTERVIEW: frozenset({Stage.OFFER, Stage.REJECTED, Stage.WITHDRAWN}),
    Stage.OFFER: frozenset({Stage.ACCEPTED, Stage.DECLINED, Stage.WITHDRAWN}),
    Stage.ACCEPTED: frozenset(),
    Stage.DECLINED: frozenset(),
    Stage.REJECTED: frozenset(),
    Stage.WITHDRAWN: frozenset(),
}


@dataclass(frozen=True)
class Application:
    """One position plus the evidence needed to act on it deliberately."""

    id: int
    company: str
    role: str
    source: str | None
    stage: Stage
    priority: int
    applied_on: date | None
    next_action: str | None
    next_action_due: date | None
    notes: str
    created_at: datetime
    updated_at: datetime
    version: int


def clean_required(value: str, *, field: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise ValueError(f"{field} must not be blank")
    return cleaned


def clean_optional(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


def validate_priority(priority: int) -> int:
    if isinstance(priority, bool) or not isinstance(priority, int) or not 1 <= priority <= 5:
        raise ValueError("priority must be an integer from 1 to 5")
    return priority


def validate_transition(current: Stage, target: Stage) -> None:
    if target not in STAGE_TRANSITIONS[current]:
        raise ValueError(f"cannot move an application from {current.value} to {target.value}")


def parse_stage(value: str) -> Stage:
    try:
        return Stage(value)
    except ValueError as exc:
        choices = ", ".join(stage.value for stage in Stage)
        raise ValueError(f"stage must be one of: {choices}") from exc
