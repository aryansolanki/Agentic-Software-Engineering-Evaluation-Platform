# Runta Integration

## Role of Runta

Runta is the execution substrate for the platform, not an ornamental dependency. The product relies on isolated persistent runtimes, checkpoint restore, files/exec, egress governance, lifecycle controls, and tenant-secret injection.

## Runtime lifecycle used by a product run

```text
create baseline
    |
prepare repository
    |
validate baseline
    |
create checkpoint
    |
restore N candidate runtimes concurrently
    |
run coding workers + tests
    |
retain or delete runtimes according to run settings
```

## Checkpoint fan-out

Checkpoint restore lets every candidate start from the same prepared repository/dependency state. This reduces repeated setup cost and removes variation caused by candidates starting from slightly different environments.

## Secret configuration

The local control plane stores the OpenAI credential as a Runta tenant secret using the SDK secret manager.

The installed `runta-sdk==0.2.5` public runtime manager does not expose `secret_configuration` in its high-level `create()` signature, while the generated v2 API model does. The project therefore creates secret-enabled candidate/judge runtimes through the v2 runtime creation API shape and includes `secret_configuration` atomically at creation time.

The relevant egress rule is conceptually:

```text
host: api.openai.com
path: /v1/*
header: Authorization
value template: Bearer ${secret}
```

No post-create secret-stub mutation is required.

## Egress

Candidate runtime creation can include an allowlist for hosts needed by the repository task, such as package registries. `api.openai.com` is included for model access when the coding worker is used.

The separate experiment harness also verifies allowed/blocked outbound behavior.

## Files and snapshots

The product uses runtime files for worker upload and small reads/writes. For complete workspace export it generates a source-only ZIP inside the runtime, then downloads that file. This avoids unsafe symlink archives from repository-local virtual environments.

## Additional capability experiments

The CLI includes independent experiments for:

- preflight health/list;
- runtime/files/exec;
- checkpoint/fork;
- concurrent fan-out;
- egress + lifecycle;
- memory behavior;
- ingress + auto-suspend/wake;
- cleanup.

These experiments are intentionally separate from the product workflow so infrastructure behavior can be tested in isolation.
