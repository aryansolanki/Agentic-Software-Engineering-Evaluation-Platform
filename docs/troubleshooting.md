# Troubleshooting

This document records the failure classes encountered while making the product work end to end and the current resolution.

## `python: not found`

Some runtime images expose `python3` but not a `python` alias.

Use:

```bash
python3 ...
```

or a repository-local virtualenv interpreter.

## PEP 668 / externally-managed Python environment

Installing packages directly into the system interpreter can fail with an `externally-managed-environment` error.

Preferred fix:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements-dev.txt
```

Avoid `--break-system-packages` for normal repository setup.

## Runtime directory download rejects an unsafe link

Repository-local virtual environments commonly contain symlinks. Runta's safe archive extraction can reject a raw directory download containing unsafe links.

Current solution: the runtime first creates a source-only ZIP that excludes virtualenvs, dependency directories, caches, Git metadata, bytecode, and symlinks. The local control plane downloads that file instead of the raw repository directory.

## Empty candidate diff

Relying on remote `git diff` was brittle because exported workspaces may not preserve Git metadata or an agent could alter repository state.

Current solution: capture an immutable baseline source snapshot and compare it locally against the final candidate source snapshot.

## Secret configuration API mismatch

`runta-sdk==0.2.5` exposes tenant secret management publicly but not runtime `secret_configuration` in the high-level runtime create method.

The project uses the v2 runtime-create request shape for secret-enabled candidate/judge creation. This avoids retired secret-stub routes and revision-sensitive post-create mutation.

## `secret value_template must contain ${secret}`

The Runta v2 egress secret template requires `${secret}` exactly once.

Current value:

```text
Bearer ${secret}
```

## Baseline repository setup fails

The orchestrator treats clone/setup failures as fatal. Verify:

- public HTTPS Git URL;
- required package registry egress hosts;
- interpreter name (`python3` vs `python`);
- virtualenv setup;
- repository-specific dependency filename;
- repository-specific test command.

## All candidates fail

This is a valid run outcome. The platform intentionally selects no winner when no candidate passes deterministic validation.

Inspect candidate test output, agent output/status, and diff rather than assuming the ranking should always contain a winner.
