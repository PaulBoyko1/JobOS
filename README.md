# JobOS

**A local-first operating system for a thoughtful job search.**

JobOS treats a job search as a sequence of accountable decisions rather than an inbox full of tabs. It keeps applications, next actions, priorities, and an append-only activity trail in one portable SQLite database. It deliberately avoids scraping, account creation, and opaque scoring.

## Why it exists

A job search often fails quietly: a strong opportunity is forgotten, a follow-up goes stale, or a decision is made from scattered notes. JobOS makes the operating cadence visible:

- capture a role with its source and priority
- move it through an explicit, valid workflow
- schedule the next concrete action
- surface overdue follow-ups before they disappear
- retain a durable event history for reflection and improvement

## Core ideas

| Idea | JobOS behavior |
| --- | --- |
| Local-first | The entire system is one SQLite file you own. |
| Workflow integrity | Illegal jumps, such as saved directly to offer, are rejected. |
| Deliberate action | A date without a next action is rejected. |
| Auditability | Each creation, stage change, and action update is recorded. |
| Conflict awareness | Optimistic versioning prevents one stale update from overwriting another. |

## Quick start

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'

jobos init data/jobos.sqlite3
jobos add data/jobos.sqlite3 \
  --company "Northstar Labs" \
  --role "Systems Engineer" \
  --source "Referral" \
  --priority 5

jobos plan data/jobos.sqlite3 1 \
  --action "Research the team and prepare a tailored note" \
  --due 2026-08-12 \
  --version 1

jobos dashboard data/jobos.sqlite3
```

Every mutation prints the application's current version. Pass that value back with `--version` for the next update.

## Workflow

```text
saved -> applied -> screen -> interview -> offer -> accepted / declined
                 \-> rejected / withdrawn at any active stage
```

Terminal applications cannot receive new next actions. This keeps the dashboard focused on decisions that still need attention.

## Architecture

```text
CLI
 |
 v
JobOS service: validation, workflow policy, daily dashboard
 |
 v
SQLite store: applications + append-only event trail
```

The package uses the Python standard library at runtime. The development toolchain adds Ruff, mypy, pytest, and package builds in GitHub Actions.

## What makes it useful in a portfolio

JobOS demonstrates more than CRUD:

- state-machine design with domain-specific transitions
- local persistence and SQL schema design
- optimistic concurrency control
- decision-support prioritization
- testable business rules with no external-service dependency

## Responsible use

JobOS stores only the information you choose to record. Keep sensitive notes in a protected location, avoid putting credentials in the database, and use the tool to support a fair, deliberate process rather than automated applicant screening.

## Development

```bash
ruff check .
mypy src
pytest
python -m build
```
