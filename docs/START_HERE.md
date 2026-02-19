# Start Here

Use this page as the single docs entrypoint.

Documentation hub:
- `docs/README.md` (how docs are structured and maintained)
- `docs/LEARNING_PATHS.md` (guided curriculum for operators/developers)

## Pick your role

### Operator path
1. `docs/DAY1_DEPLOY_CHECKLIST.md` for first production rollout.
2. `docs/RUNBOOK.md` for daily operations and maintenance commands.
3. `docs/TROUBLESHOOTING.md` for symptom-first incident triage.
4. `docs/SECURITY.md` for retention/privacy/security boundaries.
5. `docs/DISASTER_RECOVERY.md` for rebuild/restore procedure.
6. `docs/BOOTSTRAP_SERVER.md` for fresh server bootstrapping.

### Teacher/staff path
1. `docs/WHAT_WHERE_WHY.md` for plain-language system orientation.
2. `docs/TEACHER_PORTAL.md` for teacher UI workflow (`/teach`).
3. `docs/COURSE_AUTHORING.md` for curriculum updates.
4. `docs/TEACHER_HANDOFF_CHECKLIST.md` for staffing transitions.
5. `docs/TEACHER_HANDOFF_RECORD_TEMPLATE.md` for handoff recordkeeping.

### Developer path
1. `docs/ARCHITECTURE.md` for service boundaries and routing.
2. `docs/DEVELOPMENT.md` for local dev workflow.
3. `docs/LEARNING_PATHS.md` for guided end-to-end exercises.
4. `docs/DECISIONS.md` for change rationale and tradeoffs.
5. `docs/TEACHING_PLAYBOOK.md` for documentation quality and teaching standards.
6. `docs/REQUEST_SAFETY.md` for shared IP/rate-limit helpers.
7. `docs/OPENAI_HELPER.md` and `docs/HELPER_POLICY.md` for helper backend/prompt behavior.
8. `docs/HELPER_EVALS.md` for evaluation workflow.

## Canonical URL map

- Student join: `/`
- Student class view: `/student`
- Teacher portal: `/teach`
- Teacher lessons: `/teach/lessons`
- Teacher videos: `/teach/videos`
- Admin login: `/admin/login/`
- Classhub health: `/healthz`
- Helper health: `/helper/healthz`

## Canonical setup/deploy paths

- Local quickstart: `README.md#quickstart-local`
- Full self-check: `bash scripts/system_doctor.sh`
- Production rollout: `docs/DAY1_DEPLOY_CHECKLIST.md`
- Guardrailed deploy command: `bash scripts/deploy_with_smoke.sh`
