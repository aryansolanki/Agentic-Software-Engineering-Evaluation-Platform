# Architecture

## System boundary

The platform intentionally separates a lightweight local **control plane** from a remote **execution plane**.

```text
Browser
  |
  v
FastAPI dashboard/API
  |
  +--> SQLite run/evidence store
  +--> orchestrator
  +--> local scoring/export
             |
             v
          Runta API
             |
   +---------+----------+
   |                    |
   v                    v
baseline runtime    judge runtime (optional)
   |
checkpoint
   |
   +--> candidate runtime 1
   +--> candidate runtime 2
   +--> ...
   +--> candidate runtime N
```

## Local control plane

### FastAPI dashboard/API

`src/runta_agent_eval/api/app.py` exposes the browser UI and run/download endpoints.

The dashboard lets a user configure:

- task name and instructions;
- built-in fixture or public Git source;
- candidate count;
- Deterministic / AI Judge / Hybrid evaluation;
- setup and test commands;
- additional allowed egress hosts;
- whether runtimes should be retained for inspection.

### Orchestrator

`services/orchestrator.py` is the central workflow coordinator. It:

1. creates the baseline runtime;
2. prepares the repository;
3. validates the baseline test command;
4. captures the immutable baseline source snapshot;
5. creates a Runta checkpoint;
6. restores N candidate runtimes concurrently;
7. uploads and executes the coding worker in each candidate;
8. reruns tests independently;
9. downloads source-only candidate snapshots;
10. generates local baseline-vs-candidate diffs;
11. evaluates/ranks candidates;
12. persists run/candidate evidence;
13. selects a winner only from deterministically passing candidates.

### SQLite evidence store

The database records runs, candidate states/scores, diffs, test output, agent output, winner selection, and optional observations. SQLite keeps the public project self-contained; it is not intended as a distributed production persistence layer.

## Runta execution plane

### Baseline runtime

The baseline runtime is the only environment that performs initial repository preparation. For public Git sources this includes clone and optional dependency setup. The configured baseline test command is run before candidate fan-out.

### Checkpoint

After preparation, a checkpoint captures the common starting state. This is the key fairness and efficiency primitive: every candidate begins from equivalent repository contents and dependencies.

### Candidate runtimes

Each candidate is restored independently from the checkpoint and receives its own coding strategy. Filesystem changes, commands, and agent state are isolated per runtime.

### Judge runtime

AI Judge and Hybrid modes create a separate Runta runtime for engineering-quality review. The judge receives bounded evidence rather than direct mutable access to candidate workspaces.

## Artifact flow

Direct directory downloads can contain disposable environments or symlinks. The project therefore creates a source-only ZIP snapshot inside each runtime.

Excluded from snapshots include:

- `.venv` / `venv`;
- `.git`;
- `__pycache__` and bytecode;
- `.pytest_cache`;
- `node_modules`;
- symlinks.

The local control plane safely extracts the snapshot and compares it against the immutable baseline snapshot to generate the candidate diff.

## Why this shape

The architecture keeps orchestration and evidence management lightweight locally while moving untrusted autonomous code execution into isolated remote runtimes. It also makes parallelism explicit: adding candidates means restoring more independent runtime branches rather than multiplexing several agents inside one shared filesystem.
