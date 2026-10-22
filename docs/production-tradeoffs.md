# Production Trade-offs

## What the current project optimizes for

The implementation is intentionally focused on the engineering-evaluation problem:

- isolated coding environments;
- fair checkpoint-based candidate starts;
- agent reliability;
- deterministic correctness evidence;
- qualitative ranking;
- safe source artifact export.

It avoids adding unrelated product infrastructure merely to make the architecture look larger.

## Local FastAPI + SQLite

A single local process and SQLite database are appropriate for a developer-operated evaluation tool. They make the repository reproducible and easy to inspect.

A hosted multi-user service would likely need:

- Postgres or another shared transactional store;
- durable distributed job orchestration;
- idempotent run state transitions;
- explicit cancellation/retry ownership;
- authentication/RBAC;
- multi-tenant artifact storage.

## Synchronous dashboard polling

The UI polls `/api/runs` rather than maintaining a streaming connection. This keeps the frontend dependency-free but gives limited visibility into long agent steps.

A production UI would benefit from server-sent events or WebSockets for runtime/agent progress.

## Public Git only

The current public-repository path avoids private Git credentials. Production support would need a GitHub App or short-lived credential broker, careful secret scoping, and repository authorization checks.

## Simple deterministic scoring

Patch-size scoring is intentionally lightweight. For broader tasks, deterministic evaluation could include:

- repository-specific quality gates;
- lint/type-check/build commands;
- hidden tests;
- mutation/regression tests;
- test coverage deltas;
- forbidden-file policy;
- security/static analysis.

## AI Judge

The judge is useful for qualitative comparison but remains probabilistic. Production use should log judge prompts/results, version judge policies, support re-evaluation, and measure agreement against human reviewer choices.

## Candidate cost

Parallelism improves search diversity but multiplies runtime and model consumption. A production scheduler should expose estimated/actual cost and support budget-aware stopping.

## Sandbox policy

Runta supplies the runtime isolation/governance layer used here, but safe autonomous execution remains a broader system concern. A production service should define repository trust tiers, network policies, resource limits, command policies, and artifact-retention rules.
