# Real Repository Validation

## Goal

The controlled fixture proves that the orchestrator can solve a known deterministic bug, but it does not prove that the same architecture works on an unfamiliar repository with dependency setup and real Git history.

The final validation therefore used a public Python calculator repository and a feature request that required inspecting its existing AST-based evaluator.

## Repository and task

Repository used during validation:

```text
https://github.com/appstiwari/py-calculator.git
```

Task:

```text
Add exponentiation support to the calculator core.

Requirements:
- Support the ** operator for numeric expressions.
- Preserve the existing safe AST-based evaluation approach.
- Do not use eval() or exec().
- Do not modify or delete existing tests.
- You may add new tests if appropriate.
- Keep all existing operators working.
- Keep the implementation patch minimal.
- Run the complete test suite and ensure it passes.
```

Setup command used:

```bash
python3 -m venv .venv && \
.venv/bin/python -m pip install --upgrade pip && \
.venv/bin/python -m pip install -r requirements-dev.txt
```

Test command:

```bash
.venv/bin/python -m pytest -q
```

Additional egress hosts:

```text
github.com,pypi.org,files.pythonhosted.org
```

## Pipeline exercised

```text
public Git clone
    |
repository-local virtualenv + dependencies
    |
baseline tests
    |
source-only baseline snapshot
    |
Runta checkpoint
    |
5 independent candidate restores
    |
autonomous coding agents
    |
independent tests
    |
source-only candidate snapshots
    |
baseline-vs-candidate diffs
    |
deterministic + AI Judge
    |
Hybrid ranking + winner export
```

## Result

All five candidates passed the full repository test command with exit code `0`.

| Candidate | Deterministic | AI | Final | Rank |
| --- | ---: | ---: | ---: | ---: |
| 1 | 99.8 | 97.0 | **98.8** | **1** |
| 4 | 99.7 | 95.0 | 98.1 | 2 |
| 5 | 99.7 | 94.0 | 97.7 | 3 |
| 2 | 99.5 | 90.0 | 96.2 | 4 |
| 3 | 99.4 | 88.0 | 95.4 | 5 |

Candidate 1 was selected as the winner.

## Diversity observed

The solutions were not identical retries:

- Candidate 1 used a highly minimal `ast.Pow` implementation.
- Candidates 4/5 also updated the supported-operator documentation.
- Candidate 2 wrapped exponentiation in broad exception conversion.
- Candidate 3 added narrower error handling and rejected complex results.

The deterministic scores were close because every patch was small and all tests passed. The AI judge then differentiated the engineering trade-offs and produced a useful final ordering.

## Artifact validation

The run also verified that:

- repository-local `.venv` can remain available for tests;
- disposable environment files/symlinks are excluded from exported snapshots;
- candidate source diffs remain non-empty and readable;
- winner, non-winner, all-candidate, and individual downloads are generated.

## Screenshots

### Task configuration

![Task configuration](images/task-configuration.png)

### Hybrid result

![Five candidate Hybrid result](images/five-candidate-hybrid-result.png)

### Candidate diff

![Candidate diff](images/candidate-diff.png)
