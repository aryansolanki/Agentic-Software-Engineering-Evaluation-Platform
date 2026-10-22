# Changelog

## 0.3.9

Current public portfolio baseline.

### Agent execution

- persistent multi-step action/result context;
- deterministic working-state memory;
- repeated-action loop guard;
- exact `replace` edit tool in addition to full-file writes;
- configured test-command awareness;
- verified `finish` behavior;
- candidate-specific engineering strategies;
- explicit worker outcome/status handling.

### Evaluation

- deterministic correctness gate;
- AI judge normalization and score clamping;
- Hybrid `65% deterministic / 35% AI` score;
- no-winner outcome when no candidate passes deterministic validation;
- passing candidates always outrank failing candidates for winner eligibility.

### Runta integration

- tenant OpenAI secret storage;
- runtime creation with v2 `secret_configuration`;
- matching outbound OpenAI requests receive injected Authorization headers;
- checkpoint-based candidate fan-out;
- optional judge runtime;
- project cleanup and capability experiments.

### Artifacts and real repositories

- baseline-vs-candidate source diff generation;
- public Git repository clone/setup/test flow;
- fail-fast setup errors;
- source-only runtime snapshots;
- `.venv`, Git internals, caches, `node_modules`, bytecode, and symlinks excluded from exported snapshots;
- path-traversal checks during local snapshot extraction.

### Validation

- 28 local tests passing;
- controlled fixture end-to-end success;
- public Git repository end-to-end success;
- five-candidate Hybrid public-repository run with all candidates passing and AI-assisted ranking.
