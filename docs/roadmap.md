# Roadmap

The core project goal is complete: controlled and real public repositories can be checkpointed, fanned out across multiple Runta candidates, solved by autonomous agents, evaluated deterministically and with an AI judge, ranked, and exported.

The remaining work is productization rather than core feasibility.

## Highest-value next steps

### Run control

- cancel an active run;
- retry only failed candidates;
- rerun evaluation without rerunning agents;
- configurable per-candidate timeout/budget;
- stop early when an acceptance threshold is reached.

### Visibility

- streaming agent/runtime timeline;
- step-by-step action transcript in the dashboard;
- judge rationale UI;
- runtime duration, token, and cost metrics;
- candidate cards sorted by final rank.

### Repository integration

- private repositories through a GitHub App;
- branch/commit pinning;
- issue/PR task import;
- winner branch export;
- optional PR creation with evidence summary.

### Evaluation

- multiple deterministic commands (tests + lint + type-check + build);
- hidden evaluator tests;
- forbidden-path/test-tampering policy;
- test coverage deltas;
- configurable scoring policies;
- human reviewer feedback and judge calibration.

### Platform hardening

- Postgres persistence;
- durable queue/workflow engine;
- object storage for artifacts;
- authentication and multi-tenancy;
- structured telemetry and tracing;
- retention/cleanup policies;
- versioned runtime/agent/judge configuration.
