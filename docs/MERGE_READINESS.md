# Branch Merge Readiness Checklist

Use this before you ask for review. This is the "no surprises" ritual.

## 1) Scope + intent check (2 minutes)

- Can you explain the change in one sentence without buzzword fog?
- Does the change map to one of our North Star outcomes (reliable / inspectable / privacy-forward / fast to ship)?
- Did you avoid side quests unrelated to the branch goal?

If any answer is "no", tighten scope before review.

## 2) Product constraint check (hard gates)

- Student access is still class code + display name in MVP.
- Teacher/admin auth still uses Django auth.
- Homework Helper still routes under `/helper/*`.
- Hosted LLM integrations are aligned with Responses API direction.

If you break a hard constraint, this is not "just a follow-up" — fix it now or document a formal decision.

## 3) Local verification commands

From repo root:

```bash
DJANGO_DEBUG=1 DJANGO_SECRET_KEY=dev-secret python services/classhub/manage.py check
DJANGO_DEBUG=1 DJANGO_SECRET_KEY=dev-secret python services/classhub/manage.py test
DJANGO_DEBUG=1 DJANGO_SECRET_KEY=dev-secret python services/homework_helper/manage.py check
DJANGO_DEBUG=1 DJANGO_SECRET_KEY=dev-secret python services/homework_helper/manage.py test
```

For stack-level confidence:

```bash
bash scripts/smoke_check.sh
```

If any command fails because of local environment constraints, note that explicitly in PR notes.

## 4) Docs + decision hygiene

- Updated docs for behavior changes (not just code).
- Added or amended `docs/DECISIONS.md` when making a design/policy tradeoff.
- Kept language operator-usable and teacher-readable.

No docs update for behavior change = incomplete branch.

## 5) Review ergonomics (make reviewer life easy)

- PR title says what changed and why.
- PR body includes:
  - problem statement
  - change summary
  - risk + rollback notes
  - exact validation commands + outcomes
  - link to CI coverage artifacts (`coverage-classhub.xml`, `coverage-helper.xml`) when test-suite runs
- Keep commit history coherent (squash fixup noise if needed).

## 6) Data/privacy sanity check

- No accidental PII expansion.
- No secrets committed.
- Logging changes preserve inspectability without oversharing student data.

## 7) Deployment sanity check

- Migration impact is explained.
- Any ops step changes reflected in runbook/checklists.
- Changes are reversible (or rollback strategy is documented).

---

If this feels strict, good. We’re optimizing for calm operations, not adrenaline deployments.
