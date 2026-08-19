# TokenStore deepening — single Access Token module

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make TokenStore the only deep Access Token module: one place for current token, bearer check, env override, and rotate; auth and Setup call it through get_token_store().

**Architecture:** Expand–contract. Task 1 deepens TokenStore while keeping thin module delegates. Task 2 migrates callers and deletes duplicates. ADR 0021 (secrets file + env override + rotate) unchanged in behaviour.

**Tech Stack:** Python 3, `serial_bridge.token_store` / `auth` / `setup`, unittest under `tests/`.

**Tickets:** `.scratch/serial-bridge-mcp/issues/07`–`08`

---

## Global Constraints

- Do not change Access Token behaviour (env override, file persistence, rotate semantics, loopback exemption).
- Do not change MCP tool return shapes or Hub Exec/mode internals.
- Do not rewrite Setup UI beyond calling the TokenStore seam.
- Prefer CONTEXT.md vocabulary: Access Token, Setup Page, MCP Server, Operator.
- TDD where behaviour moves; focused tests while iterating; full suite before commit.
- Commit after each task with a why-focused message.
- Work only in `D:\SourceCode\serial_bridge\.worktrees\serial-bridge-mcp` on `feature/serial-bridge-mcp`.

---

## Task 1: Expand TokenStore as the Access Token source of truth

**Ticket:** `.scratch/serial-bridge-mcp/issues/07-tokenstore-expand.md`

**Blocked by:** None

**What to build:** TokenStore owns current token (env included), bearer check, env-override flag, and rotate; module helpers become thin delegates; auth/Setup behaviour unchanged.

### Steps

- [ ] Write/extend failing tests that exercise TokenStore methods for current token, valid_bearer, env_overrides, and rotate (including env-override still true after rotate).
- [ ] Implement those methods on TokenStore as the single implementation; point module-level `runtime_access_token` / `valid_bearer_token` / `env_overrides_token` / `rotate_access_token` at the store (or store methods) so callers need not change yet.
- [ ] Run token_store (+ related) tests and full suite; commit.

### Acceptance

- TokenStore holds the real logic for token/bearer/env/rotate.
- Module helpers only delegate.
- Existing focused tests pass.

---

## Task 2: Contract — auth + Setup call TokenStore only

**Ticket:** `.scratch/serial-bridge-mcp/issues/08-tokenstore-contract.md`

**Blocked by:** Task 1

**What to build:** auth and Setup use get_token_store(); delete duplicate module-level helpers; behaviour unchanged.

### Steps

- [ ] Migrate auth.py and setup.py to get_token_store() methods; update tests that imported deleted helpers.
- [ ] Remove duplicate module-level token helpers (keep init/get/reset/load as needed for process lifecycle).
- [ ] Run auth/setup/token tests and full suite; commit.

### Acceptance

- No parallel valid_bearer_token / runtime_access_token paths.
- MCP Bearer, non-loopback send auth, Setup display/rotate unchanged.
- Suite green.

---

## Execution order (SDD)

Serially: 1 → 2.
