# Learning Paths

This repository is intentionally both a production tool and a teaching object.
Use these paths to learn progressively with concrete checkpoints.

How to use this page:
- Pick one path and complete it end-to-end before jumping ahead.
- Capture notes as "what surprised me" and "what would fail silently."
- Treat each lab as a production rehearsal, not a reading exercise.

## Path 1: Operator Fundamentals

Goal:
- bring the system up safely
- validate health and routing
- recover from common outages

Time budget:
- 60 to 90 minutes

Read in order:
1. `docs/START_HERE.md`
2. `docs/DAY1_DEPLOY_CHECKLIST.md`
3. `docs/RUNBOOK.md`
4. `docs/TROUBLESHOOTING.md`
5. `docs/SECURITY.md`

Hands-on lab:

1. Start services:
```bash
cd /srv/lms/app/compose
docker compose up -d --build
```
2. Verify health endpoints:
```bash
curl -I http://localhost/healthz
curl -I http://localhost/helper/healthz
```
3. Verify caddy mount source:
```bash
docker inspect classhub_caddy --format '{{range .Mounts}}{{println .Source "->" .Destination}}{{end}}'
```
4. Run safety guards:
```bash
cd /srv/lms/app
bash scripts/validate_env_secrets.sh
python3 scripts/check_compose_port_exposure.py
```

Expected outcomes:
- both health checks return `200`
- caddy mount points to intended Caddyfile template
- env and port guard scripts return success

Deliverable:
- a short run log containing command timestamps and outcomes.

Debrief prompts:
- Which check would have caught a bad domain config first?
- Which output is the strongest signal that routing is correct?

## Path 2: Application Architecture

Goal:
- understand service boundaries
- understand where identity/session/routing decisions live

Time budget:
- 75 to 120 minutes

Read in order:
1. `docs/WHAT_WHERE_WHY.md`
2. `docs/ARCHITECTURE.md`
3. `docs/CLASS_CODE_AUTH.md`
4. `docs/REQUEST_SAFETY.md`
5. `docs/DECISIONS.md`

Hands-on lab:

1. Trace helper request path:
  - browser request to `/helper/chat`
  - caddy route to `helper_web`
  - helper auth + scope checks
  - backend call and response envelope
2. Trace student request path:
  - join with class code
  - session creation
  - class material view

Suggested verification commands:
```bash
cd /srv/lms/app/compose
docker compose logs --tail=120 caddy
docker compose logs --tail=120 helper_web
docker compose logs --tail=120 classhub_web
```

Deliverable:
- one diagram (whiteboard or markdown) that shows request flow for:
  - `/student`
  - `/helper/chat`

Debrief prompts:
- What dependency does helper have on classhub data at request time?
- Where can auth/session assumptions leak across service boundaries?

## Path 3: Helper Safety and Scope Controls

Goal:
- understand scope-token model
- understand anti-cheating and topic filters
- understand fail-open vs fail-closed knobs

Time budget:
- 60 to 90 minutes

Read in order:
1. `docs/HELPER_POLICY.md`
2. `docs/OPENAI_HELPER.md`
3. `docs/REQUEST_SAFETY.md`
4. `docs/SECURITY.md`
5. `docs/HELPER_EVALS.md`

Key invariants to internalize:
- students require signed scope tokens
- unsigned scope fields are ignored
- staff can be forced to require tokens (`HELPER_REQUIRE_SCOPE_TOKEN_FOR_STAFF=1`)
- classhub table requirement is configurable (`HELPER_REQUIRE_CLASSHUB_TABLE`)

Hands-on lab:

1. Run helper auth tests:
```bash
cd /srv/lms/app/compose
docker compose exec -T helper_web python manage.py test tutor.tests.HelperChatAuthTests
```
2. Run full helper suite:
```bash
docker compose exec -T helper_web python manage.py test tutor.tests
```
3. Trigger strict policy behavior manually:
  - ask out-of-scope question from student view
  - confirm policy redirect language appears

Expected outcomes:
- helper auth suite passes.
- strict mode produces policy guidance instead of unrestricted model output.
- logs include structured auth/policy events with `request_id`.

Deliverable:
- a one-page "trust boundaries" note:
  - trusted inputs
  - untrusted inputs
  - fallback behavior when classhub tables are unavailable

Debrief prompts:
- What attack is prevented by ignoring unsigned scope fields?
- What user-facing tradeoff exists between strict and soft topic filtering?

## Path 4: Teacher Workflow and Content Operations

Goal:
- manage classes and teacher onboarding safely
- understand authoring and rebuild flows

Time budget:
- 60 to 100 minutes

Read in order:
1. `docs/TEACHER_PORTAL.md`
2. `docs/COURSE_AUTHORING.md`
3. `docs/TEACHER_HANDOFF_CHECKLIST.md`
4. `docs/TEACHER_HANDOFF_RECORD_TEMPLATE.md`

Hands-on lab:

1. Create/update course pack:
```bash
cd /srv/lms/app
scripts/rebuild_coursepack.sh --course-slug piper_scratch_12_session --create-class
```
2. Verify teacher portal routes and actions:
  - `/teach`
  - `/teach/lessons`
  - `/teach/videos`
3. Validate invite and 2FA setup flow in staging before production use.

Expected outcomes:
- course content imports without parser errors.
- teacher routes render and allow expected actions.
- invite and OTP setup are reproducible on a clean teacher account.

Deliverable:
- a staging checklist run with pass/fail for:
  - content rebuild
  - teacher login
  - invite setup
  - OTP verification

Debrief prompts:
- Which teacher task is most likely to fail after content schema changes?
- Which checks should be required before onboarding new staff?

## Path 5: Secure Change Delivery

Goal:
- practice shipping changes with guardrails
- connect local checks to CI checks

Time budget:
- 45 to 75 minutes

Read in order:
1. `docs/DEVELOPMENT.md`
2. `docs/MERGE_READINESS.md`
3. `docs/SECURITY.md`
4. `docs/DECISIONS.md`

Hands-on lab:

1. Run lint/test/security checks locally (where available):
```bash
cd /srv/lms/app
bash scripts/migration_gate.sh
python3 scripts/check_compose_port_exposure.py
```
2. Run deployment smoke checks:
```bash
bash scripts/smoke_check.sh --strict
```
3. Run guarded deployment script in staging:
```bash
bash scripts/deploy_with_smoke.sh
```
4. Run full stack doctor:
```bash
bash scripts/system_doctor.sh --smoke-mode golden
```

Expected outcomes:
- migration gate and smoke checks pass with no manual patch-up.
- deployment command exits successfully with healthy services.
- reviewer can map local checks directly to CI safety intent.

Deliverable:
- a mock change report with:
  - risk statement
  - checks run
  - rollback trigger conditions

Debrief prompts:
- Which check most reduces the probability of a production outage?
- Which failures are acceptable to defer, and which are hard stop?

## Teaching notes for maintainers

When adding features, include:
- one architecture sentence ("what boundary changed")
- one decision sentence ("why we chose this")
- one operator check ("how to verify post-deploy")
- one failure mode ("what breaks first if misconfigured")

That pattern keeps this repo teachable without inflating every doc page.
