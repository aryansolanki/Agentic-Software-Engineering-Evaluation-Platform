# Security and Secrets

## Threat model for this project

Autonomous coding agents execute repository commands and can make arbitrary source changes. The project therefore treats candidate runtimes as execution sandboxes and avoids directly embedding long-lived model credentials into candidate code or ordinary environment variables.

## Credential flow

```text
local .env
   |
   | OPENAI_API_KEY
   v
local control plane
   |
   | store/update
   v
Runta tenant secret
   |
   | runtime secret_configuration
   v
matching OpenAI HTTPS request
   |
   +--> Authorization: Bearer <injected secret>
```

The runtime configuration uses no environment injection for the OpenAI key. The secret is used to populate the outbound Authorization header for matching OpenAI requests.

## Egress governance

Users can provide additional allowed hosts needed for repository setup, such as package registries. Candidate runtimes receive an egress policy at creation time.

The security value is not that every possible malicious repository is made safe; rather, autonomous execution is placed inside isolated runtimes with explicit network policy instead of directly on the developer laptop.

## Source artifact safety

Workspace export deliberately excludes:

- virtual environments;
- Git internals;
- dependency directories;
- caches and bytecode;
- symlinks.

Local ZIP extraction validates paths to prevent archive traversal outside the intended destination.

## Local secret hygiene

`.env` is ignored by Git. `.env.example` contains only variable names/defaults and should never contain real credentials.

Before publishing a fork or derivative project, run a secret scan or at minimum inspect staged Git content before the first push.

## Current limitations

The project is not a complete hostile-code security product. It does not currently provide:

- per-task policy templates beyond configured egress hosts;
- malware scanning of downloaded repositories;
- organization-level secret/RBAC policy;
- private-repository credential brokering;
- signed provenance for candidate artifacts;
- centralized audit log retention.
