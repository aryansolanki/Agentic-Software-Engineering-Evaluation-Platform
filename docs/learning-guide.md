# Learning Guide

This guide explains the project from the perspective of an engineer who wants to understand **why each layer exists**, how a run moves through the codebase, and what trade-offs the implementation makes.

## 1. The product idea

A normal coding-agent workflow asks one model to modify one repository and hopes the result is good. This project treats software engineering more like a search-and-evaluation problem:

```text
same task + same prepared repository
              |
              v
     multiple independent attempts
              |
              v
 objective correctness + quality review
              |
              v
          best valid result
```

The difficult part is not merely calling an LLM. The difficult parts are reproducible environments, isolation, fair starting state, reliable agent memory, deterministic validation, failure semantics, safe credential delivery, artifact capture, and ranking.

## 2. Entry points

### CLI

`src/runta_agent_eval/cli.py`

The `runta-eval` command provides:

- `serve` for the product dashboard;
- `preflight` for connectivity;
- capability experiments (`level1` through `level4`, memory, autosuspend);
- cleanup for project-owned resources.

### Web application

`src/runta_agent_eval/api/app.py`

The FastAPI application initializes settings/database state and exposes endpoints for:

- creating runs;
- listing runs;
- retrieving run/candidate evidence;
- downloading winner/candidate bundles;
- recording observations.

The browser UI is a static HTML/CSS/JavaScript page in `src/runta_agent_eval/static/index.html`, so no Node/frontend build chain is required.

## 3. Request model

`core/models.py` defines a task with:

- name;
- task instructions;
- candidate count;
- evaluation mode;
- source mode (fixture or public Git);
- Git URL when applicable;
- setup command;
- test command;
- optional model override;
- allowed egress hosts;
- runtime-retention choice.

Validation requires a Git URL when public Git mode is selected.

## 4. Configuration

`core/config.py` loads `.env` into an immutable settings object.

Important settings include:

```text
RUNTA_TOKEN
OPENAI_API_KEY
OPENAI_MODEL
OPENAI_API_URL
RUNTA_VCPUS
RUNTA_MEMORY_MIB
RUNTA_MEMORY_MAX_MIB
MAX_CANDIDATES
AGENT_MAX_STEPS
```

The main rule is separation of concerns: local configuration knows the long-lived credentials, while worker runtimes receive governed network injection rather than copied secrets.

## 5. Runta gateway

`runta/gateway.py` is the adapter between product logic and Runta.

It centralizes:

- client lifecycle;
- health/list operations;
- runtime creation/deletion;
- checkpoint operations;
- exec;
- file upload/read/write/download;
- tenant-secret storage;
- secret-enabled v2 runtime creation;
- resource/egress/ingress parameters.

Keeping these calls behind one adapter prevents the orchestrator from becoming coupled to low-level SDK/REST details.

## 6. Baseline preparation

The orchestrator creates a baseline runtime before creating candidates.

### Fixture mode

The built-in calculator fixture is uploaded to `/workspace/repo`.

### Public Git mode

The runtime clones the supplied public HTTPS repository and runs the optional setup command.

### Baseline test

Before candidate fan-out, the configured test command runs against the prepared repository. This catches invalid repository/setup configurations early rather than spending candidate runtimes on a broken baseline.

### Baseline snapshot

The runtime produces a source-only ZIP snapshot. This immutable local copy later becomes the left-hand side of every candidate diff.

## 7. Checkpoint fan-out

Once preparation is complete, the baseline runtime creates a checkpoint.

Candidate runtimes are then created concurrently from that checkpoint.

Why this matters:

1. every candidate gets equivalent source and dependency state;
2. setup work is not repeated N times;
3. candidates cannot interfere through a shared filesystem;
4. the system can compare independent solution branches.

## 8. Coding worker

`workers/agent_worker.py` runs inside each candidate runtime.

Its loop is conceptually:

```text
build prompt from task + strategy + working history
                  |
                  v
              model call
                  |
                  v
          parse one action
                  |
       +----------+----------+
       |                     |
       v                     v
inspect/read/exec       write/replace
       |                     |
       +----------+----------+
                  |
                  v
         update working state
                  |
                  v
        continue or finish
```

The worker is bounded by `AGENT_MAX_STEPS`.

## 9. Why persistent context matters

An autonomous coding loop needs memory of what has already happened. Without it, the model may repeatedly rediscover the same facts or run the same failing command.

The worker therefore carries recent history plus structured working state. This is an application-level form of agent memory: enough to maintain task progress without needing an external vector store.

## 10. Edit model

Two edit styles are available:

- full-file `write` when replacement is appropriate;
- exact `replace` for a surgical edit.

The second tool is important because many software tasks require a tiny change. Rewriting an entire file creates unnecessary diff surface and regression risk.

## 11. Test discipline

The user supplies the authoritative test command.

The worker is told to use that command, and `finish` is verified by running it. After the worker exits, the orchestrator runs deterministic validation again.

That separation means:

```text
agent says "done" != candidate is accepted
```

Only evidence from the configured command establishes deterministic eligibility.

## 12. Candidate strategies

`services/orchestrator.py` contains 12 strategy prompts.

They do not prescribe code. They change the reasoning lens so parallel attempts explore different trade-offs.

Examples:

- a minimal strategy may prefer the smallest patch;
- an edge-case strategy may add defensive behavior;
- a reviewer strategy may spend more time checking regression risk;
- a test-driven strategy starts from observed requirements.

The real calculator validation demonstrated this effect: every candidate passed, but the implementations differed in documentation and exception-handling choices.

## 13. Diff generation

`services/snapshot.py` and `services/diffing.py` deliberately avoid depending on final remote Git state.

### Why not simply `git diff`?

The agent could alter Git metadata, a downloaded workspace might not preserve all repository internals, and runtime-local virtual environments can contain symlinks that are unsafe to extract directly.

### Current method

```text
baseline source-only ZIP
          +
final candidate source-only ZIP
          |
          v
local directory comparison
          |
          v
unified patch.diff
```

This makes artifact generation independent of candidate Git behavior.

## 14. Deterministic evaluator

`services/evaluation.py` first checks the test exit code.

If tests fail:

```text
score = 0
eligible = false
```

If they pass, the score begins at 100 and receives a small changed-line penalty. The intent is not to claim that fewer lines are always better; it is only a weak preference for focused solutions once correctness is established.

## 15. AI Judge

`workers/judge_worker.py` runs separately.

It compares bounded candidate evidence and returns structured JSON with an engineering-quality score and reason.

Separating the judge from the coding workers has two advantages:

- a candidate cannot directly decide its own rank;
- evaluation can be retried or changed independently of candidate execution.

## 16. Hybrid ranking

Hybrid mode uses:

```text
65% deterministic + 35% AI
```

But the eligibility gate is not weighted: a failing candidate still cannot win.

This is a useful design pattern for AI systems: **probabilistic judgment may influence preference, but deterministic invariants remain non-negotiable**.

## 17. Persistence and downloads

SQLite records evidence and status. Candidate artifacts are stored locally and can be packaged as:

- one candidate;
- winner only;
- non-winners;
- all candidates.

A candidate package can contain source workspace, diff, tests, agent output/transcript, and candidate metadata when available.

## 18. Failure model

The project distinguishes infrastructure, agent, test, and evaluation failure classes.

Examples:

```text
runtime creation failure
repository setup failure
agent provider failure
max steps
failed deterministic tests
no meaningful patch
AI judge failure
all candidates invalid
```

This matters because a multi-agent system should not convert "the process ended" into "the task succeeded."

## 19. What to discuss in an interview

A strong explanation should focus on the engineering decisions rather than saying only "I used agents."

Be prepared to explain:

- why checkpoint fan-out is better than preparing every candidate independently;
- why candidate isolation matters;
- why deterministic tests are the winner gate;
- why AI judgment is secondary evidence;
- how you stopped agent loops;
- why agent memory is structured history rather than a vector database here;
- how credentials are kept out of ordinary worker environments;
- why artifact snapshots exclude virtualenvs/symlinks;
- how the system behaves when all candidates fail;
- what you would change for private repos, multi-tenancy, cost controls, and production observability.

## 20. Recommended reading order

1. [README](../README.md)
2. [Architecture](architecture.md)
3. [Agent design](agent-design.md)
4. [Runta integration](runta-integration.md)
5. [Evaluation and ranking](evaluation-and-ranking.md)
6. [Security and secrets](security-and-secrets.md)
7. [Real repository validation](real-repository-validation.md)
8. [Production trade-offs](production-tradeoffs.md)
9. source code beginning with `services/orchestrator.py`
