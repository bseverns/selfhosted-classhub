# Documentation Index

This docs folder is organized so people can read only what they need.

If you are not a developer, start with `docs/NON_DEVELOPER_GUIDE.md`.

## Quick picks (by role)

| Role | Start here | Then read |
|---|---|---|
| Teacher / school staff | `docs/NON_DEVELOPER_GUIDE.md` | `docs/TEACHER_PORTAL.md` |
| Operator / admin | `docs/DAY1_DEPLOY_CHECKLIST.md` | `docs/RUNBOOK.md`, `docs/TROUBLESHOOTING.md` |
| Developer | `docs/DEVELOPMENT.md` | `docs/ARCHITECTURE.md`, `docs/DECISIONS.md` |

## Core docs map

### Classroom use
- `docs/NON_DEVELOPER_GUIDE.md`: plain-language day-to-day use.
- `docs/TEACHER_PORTAL.md`: teacher UI workflows.
- `docs/COURSE_AUTHORING.md`: curriculum content updates.
- `docs/TEACHER_HANDOFF_CHECKLIST.md`: staffing transitions.

### Operations
- `docs/DAY1_DEPLOY_CHECKLIST.md`: first production deployment.
- `docs/RUNBOOK.md`: routine maintenance and commands.
- `docs/RELEASING.md`: release archive packaging + verification.
- `docs/TROUBLESHOOTING.md`: symptom-first incident recovery.
- `docs/DISASTER_RECOVERY.md`: restore/rebuild flow.
- `docs/SECURITY.md`: security and privacy controls.

### Engineering
- `docs/DEVELOPMENT.md`: local development workflow.
- `docs/ARCHITECTURE.md`: service boundaries and routing.
- `docs/OPENAI_HELPER.md`: helper backend behavior.
- `docs/HELPER_POLICY.md`: tutor stance and anti-cheating policy.
- `docs/REQUEST_SAFETY.md`: IP/rate-limit safety helpers.
- `docs/HELPER_EVALS.md`: helper evaluation harness.

### Design rationale
- `docs/DECISIONS.md`: active design decisions and tradeoffs.
- `docs/decisions/archive/`: historical decision logs.

## Keep docs approachable

When editing docs:

1. Put a plain-language summary at the top.
2. Lead with "what to do now" before deep explanation.
3. Link from `docs/START_HERE.md` when adding a new major page.
4. Include one verification signal for operational instructions.

## Start page

For role-based entry and canonical URLs/commands, use `docs/START_HERE.md`.
