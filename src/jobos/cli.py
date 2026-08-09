"""Command line entry point for a local JobOS database."""

from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path

from jobos.domain import Application, Stage, parse_stage
from jobos.service import Dashboard, JobOS
from jobos.store import ApplicationStore


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="jobos", description="Local-first career operations")
    commands = parser.add_subparsers(dest="command", required=True)

    init_parser = commands.add_parser("init", help="create a JobOS database")
    init_parser.add_argument("database", type=Path)

    add_parser = commands.add_parser("add", help="record a new application")
    _add_database_argument(add_parser)
    add_parser.add_argument("--company", required=True)
    add_parser.add_argument("--role", required=True)
    add_parser.add_argument("--source")
    add_parser.add_argument("--priority", type=int, default=3)
    add_parser.add_argument("--notes", default="")

    move_parser = commands.add_parser("move", help="advance an application stage")
    _add_database_argument(move_parser)
    move_parser.add_argument("application_id", type=int)
    move_parser.add_argument("target")
    move_parser.add_argument("--version", type=int, required=True)
    move_parser.add_argument("--today", default=date.today().isoformat())

    plan_parser = commands.add_parser("plan", help="set or clear the next action")
    _add_database_argument(plan_parser)
    plan_parser.add_argument("application_id", type=int)
    plan_parser.add_argument("--action")
    plan_parser.add_argument("--due")
    plan_parser.add_argument("--version", type=int, required=True)

    list_parser = commands.add_parser("list", help="list applications")
    _add_database_argument(list_parser)
    list_parser.add_argument("--stage")

    dashboard_parser = commands.add_parser("dashboard", help="show today’s decision queue")
    _add_database_argument(dashboard_parser)
    dashboard_parser.add_argument("--today", default=date.today().isoformat())
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    try:
        if args.command == "init":
            ApplicationStore(args.database).initialize()
            print(f"Initialized {args.database}")
            return

        service = JobOS(ApplicationStore(args.database))
        if args.command == "add":
            _print_application(
                service.add_application(
                    company=args.company,
                    role=args.role,
                    source=args.source,
                    priority=args.priority,
                    notes=args.notes,
                )
            )
        elif args.command == "move":
            _print_application(
                service.move(
                    application_id=args.application_id,
                    target=parse_stage(args.target),
                    expected_version=args.version,
                    today=_parse_date(args.today),
                )
            )
        elif args.command == "plan":
            _print_application(
                service.plan_next_action(
                    application_id=args.application_id,
                    action=args.action,
                    due=_parse_date(args.due) if args.due else None,
                    expected_version=args.version,
                )
            )
        elif args.command == "list":
            stage = parse_stage(args.stage) if args.stage else None
            for application in service.applications(stage=stage):
                _print_application(application)
        elif args.command == "dashboard":
            _print_dashboard(service.dashboard(today=_parse_date(args.today)))
        else:  # pragma: no cover
            raise RuntimeError(f"unsupported command: {args.command}")
    except (KeyError, ValueError) as exc:
        parser.error(str(exc))


def _add_database_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("database", type=Path)


def _parse_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("dates must use YYYY-MM-DD") from exc


def _print_application(application: Application) -> None:
    print(
        json.dumps(
            {
                "id": application.id,
                "company": application.company,
                "role": application.role,
                "stage": application.stage.value,
                "priority": application.priority,
                "applied_on": application.applied_on.isoformat() if application.applied_on else None,
                "next_action": application.next_action,
                "next_action_due": (
                    application.next_action_due.isoformat() if application.next_action_due else None
                ),
                "version": application.version,
            },
            sort_keys=True,
        )
    )


def _print_dashboard(dashboard: Dashboard) -> None:
    summary = {
        "active_count": dashboard.active_count,
        "overdue": [_dashboard_item(application) for application in dashboard.overdue],
        "due_today": [_dashboard_item(application) for application in dashboard.due_today],
        "offers": [_dashboard_item(application) for application in dashboard.offers],
        "next_actions": [_dashboard_item(application) for application in dashboard.next_actions],
    }
    print(json.dumps(summary, indent=2))


def _dashboard_item(application: Application) -> dict[str, str | int | None]:
    return {
        "id": application.id,
        "company": application.company,
        "role": application.role,
        "stage": application.stage.value,
        "next_action": application.next_action,
        "next_action_due": application.next_action_due.isoformat() if application.next_action_due else None,
    }
