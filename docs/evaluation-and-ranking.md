# Evaluation and Ranking

## Design principle

The evaluator separates **correctness eligibility** from **engineering-quality preference**.

A model-based judge can help choose among correct implementations, but it cannot turn a failing implementation into the winner.

## Candidate evidence

For each candidate the evaluator records:

- deterministic test exit code;
- source diff;
- test output;
- agent output/status;
- candidate strategy;
- deterministic score;
- optional AI score;
- final score and rank.

## Deterministic mode

A nonzero test exit code produces a deterministic score of `0` and makes the candidate ineligible to win.

For a passing candidate, the score starts at `100` and applies a small scope penalty based on changed diff lines:

```text
scope_penalty = min(changed_lines * 0.05, 12)
deterministic = max(0, 100 - scope_penalty)
```

This is intentionally simple. The tests are the correctness gate; the line-count penalty only weakly prefers smaller patches.

## AI Judge mode

The judge runs in a separate Runta runtime and receives bounded evidence for every candidate.

Its instructions emphasize:

- correctness first;
- regression risk;
- unrelated changes;
- unnecessary complexity;
- brittleness;
- task mismatch;
- agent failure states;
- engineering quality among functionally correct candidates.

Judge JSON is normalized defensively:

- unknown/duplicate candidate rows are ignored;
- omitted candidates are added with score `0`;
- scores are clamped to `0..100`;
- malformed judge output causes a graceful fallback rather than corrupting deterministic evidence.

## Hybrid mode

When an AI score is available:

```text
final = 0.65 * deterministic + 0.35 * AI
```

If the judge fails, Hybrid degrades to the deterministic score rather than shrinking the candidate simply because AI evidence is absent.

## Winner eligibility

Ranking sorts deterministically passing candidates ahead of failing candidates. The winner is the highest-ranked eligible candidate.

If no candidate passes tests:

```text
winner = null
outcome = no_acceptable_candidate
```

This avoids a common multi-agent failure mode: presenting the highest-scoring failure as if it were a valid solution.

## Why not use only the AI judge?

Repository tests give reproducible task-specific evidence. LLM review is valuable for comparing minimality, clarity, regression risk, and design choices, but it is less reliable as the sole correctness mechanism.

The Hybrid design therefore uses deterministic evidence as the acceptance boundary and AI as a quality discriminator.
