# Decisions (active)

This file tracks current live decisions and constraints.
Historical implementation logs and superseded decisions are archived by month in `docs/decisions/archive/`.

## Active Decisions Snapshot

- [Auth model: student access](#auth-model-student-access)
- [Service boundary: Homework Helper separate service](#service-boundary-homework-helper-separate-service)
- [Routing mode: local vs domain Caddy configs](#routing-mode-local-vs-domain-caddy-configs)
- [Secret handling: env-only secret sources](#secret-handling-env-only-secret-sources)
- [Request safety and helper access posture](#request-safety-and-helper-access-posture)
- [Observability and retention boundaries](#observability-and-retention-boundaries)
- [Deployment guardrails](#deployment-guardrails)

## Archive Index

- `docs/decisions/archive/2026-02.md`
- `docs/decisions/archive/2026-01.md`

## Auth model: student access

**Current decision:**
- Students join with class code + display name.
- Same-device rejoin can use a signed HTTP-only device hint cookie.
- Cross-device rejoin uses student return code.
- Teachers/admins authenticate with Django auth credentials.

**Why this remains active:**
- Keeps student friction low while limiting impersonation risk.
- Maintains minimal student PII collection in MVP.

## Service boundary: Homework Helper separate service

**Current decision:**
- Homework Helper remains a separate Django service.
- Routing is under `/helper/*` through Caddy.
- Helper policy, limits, and failure handling are isolated from Class Hub page delivery.

**Why this remains active:**
- Protects classroom materials from helper outages.
- Preserves independent scaling and policy controls as helper traffic grows.

## Routing mode: local vs domain Caddy configs

**Current decision:**
- Unknown/no domain: use `compose/Caddyfile.local` (HTTP/local mode).
- Known domain: use `compose/Caddyfile.domain` and let Caddy manage TLS.

**Why this remains active:**
- Keeps local setup simple while preserving production-safe HTTPS behavior.
- Reduces configuration drift during deployment.

## Secret handling: env-only secret sources

**Current decision:**
- Secrets are injected via environment (`compose/.env` or deployment environment), never committed to git.
- `.env.example` stays non-sensitive and documents required knobs.

**Why this remains active:**
- Supports basic secret hygiene for self-hosted operations.
- Keeps rotation/update workflow operationally simple.

## Request safety and helper access posture

**Current decision:**
- Shared request-safety helpers are canonical for client IP parsing and burst/token limiting.
- Helper chat requires either valid student classroom session context or authenticated staff context.

**Why this remains active:**
- Prevents policy drift between services.
- Reduces abuse risk while keeping classroom usage workable behind proxies.

## Observability and retention boundaries

**Current decision:**
- Teacher/staff mutations emit append-only `AuditEvent` records.
- Student join/rejoin/upload/helper-access metadata emits append-only `StudentEvent` records.
- Retention is operator-managed using prune commands.

**Why this remains active:**
- Preserves incident traceability and accountability.
- Keeps privacy boundaries explicit by storing metadata rather than raw helper prompt/file content in event logs.

## Deployment guardrails

**Current decision:**
- Deploy path uses migration gate + smoke checks + deterministic compose invocation.
- Caddy mount source must match the expected compose config file.

**Why this remains active:**
- Prevents avoidable outages from config drift.
- Catches regressions before users encounter them.
