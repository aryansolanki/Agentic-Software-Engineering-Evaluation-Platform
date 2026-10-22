# Coding Agent Design

## Goal

Each candidate runtime runs a small autonomous coding worker that must understand a task, inspect the repository, make a focused change, run the configured test command, and stop only when deterministic validation succeeds.

## Available actions

The worker supports a deliberately small action vocabulary:

- inspect/list files;
- read files;
- execute commands;
- write files;
- exact text replacement for surgical edits;
- finish.

Restricting the action set makes behavior easier to reason about and reduces accidental tool misuse.

## Persistent working context

An earlier implementation supplied only the latest tool result to the next model turn. That caused oscillation because the model repeatedly lost prior observations.

The current worker carries forward:

- recent actions and results;
- files inspected;
- files changed;
- commands already executed;
- configured test command;
- task text;
- candidate strategy;
- deterministic working-state summary.

This lets the model reason across multiple steps instead of treating each turn as nearly stateless.

## Loop prevention

The worker detects repeated low-progress behavior such as rerunning the same test or repeating the same inspection action without an intervening edit/progress event. Repetition is blocked so the model must change its approach.

## Candidate strategy diversity

Candidates are assigned strategies by ordinal from a rotating set of 12 perspectives, including:

- minimal root-cause;
- test-driven;
- specification-first;
- regression-hunter;
- simplification;
- skeptical review;
- data-flow tracing;
- interface-contract analysis;
- edge-case focus;
- maintainability;
- alternative design;
- reviewer mindset.

The strategies are intentionally lightweight: they bias reasoning without hardcoding a solution.

## Verified finish

`finish` is not trusted as a statement of success. Before accepting completion, the worker reruns the configured repository test command. If the command fails, the agent must continue working.

The orchestrator also runs deterministic validation after the worker exits. This gives two layers of protection against premature success claims.

## Error handling

The worker surfaces explicit terminal states such as:

- finished;
- max steps reached;
- model/provider error;
- invalid action handling;
- deterministic finish validation failure.

The orchestrator maps these into candidate-level status semantics rather than collapsing every completed process into a generic evaluated state.
