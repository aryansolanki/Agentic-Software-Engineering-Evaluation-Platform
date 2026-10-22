# Experiments and Results

The repository contains a CLI experiment harness used to validate Runta capabilities separately from the main product workflow.

## Summary

| Experiment | Result | What was demonstrated |
| --- | --- | --- |
| Preflight | PASS | authenticated Runta health/list path |
| Level 1 | PASS | runtime creation, exec, file persistence |
| Level 2 | PASS | checkpoint + three child runtimes + inherited baseline |
| Level 3 | PASS | concurrent 12-runtime fan-out |
| Level 4 | PASS with timeout question | nonzero exits, egress allow/block, lifecycle behavior |
| Memory | exercised | requested/maximum memory and pressure experiment |
| Ingress | PASS | published HTTP service reachable on port-qualified URL |
| Auto-suspend | inconclusive | runtime remained running during the observed window |
| Secret injection | PASS in product runs | candidate/judge OpenAI calls authenticated through Runta secret configuration |
| Controlled fixture | PASS | autonomous code edit + tests + diff + winner |
| Public Git repository | PASS | clone/setup/checkpoint/agent/test/diff/rank/export |
| Five-candidate Hybrid | PASS | all five candidates passed; AI judge differentiated engineering quality |

## Level 1 — runtime/files/exec

Observed live behavior included successful runtime creation, remote command execution, file write/read persistence, and consistent dashboard state.

## Level 2 — checkpoint restore

A baseline was checkpointed and restored into three child runtimes. All children inherited the same baseline marker and subsequent child-specific changes remained isolated.

## Level 3 — fan-out

A 12-worker concurrent experiment completed successfully. This demonstrated that the workload can exercise multi-runtime fan-out beyond the product's typical small candidate counts.

## Level 4 — failure/governance/lifecycle

Observed behaviors included:

- intentional command exit code preserved;
- allowed egress succeeded;
- blocked egress surfaced a forbidden response;
- pause/resume worked;
- shutdown/boot worked;
- filesystem state persisted across shutdown/boot.

Command-timeout semantics remained an open infrastructure question in that experiment and are not presented as a confirmed product limitation.

## Memory experiment

A runtime was created with different requested and maximum memory values and a process gradually allocated memory beyond the initial requested value. The experiment exercised the configuration and workload pressure path but did not capture enough direct telemetry to claim a precise autoscaling mechanism or timing.

## Ingress and auto-suspend

The published service was reachable through the port-qualified runtime URL. During the observed idle window the runtime still reported `RUNNING`, so the project records auto-suspend/wake as inconclusive rather than claiming success or failure.

## Product validation

The strongest evidence comes from the finished product runs:

1. controlled fixture with autonomous repair and deterministic validation;
2. multi-candidate Hybrid fixture run;
3. real public Git repository with dependency setup and source-only snapshot export;
4. final five-candidate Hybrid repository run where every candidate passed and the judge produced differentiated scores.

See [real-repository-validation.md](real-repository-validation.md).
