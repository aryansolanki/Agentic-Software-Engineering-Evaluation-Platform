# Getting Started

This guide is the shortest path from a fresh clone to a working local dashboard backed by Runta runtimes.

## 1. Environment

The project was developed and validated from Ubuntu under WSL2 on Windows. Native Windows is fine for cloning the repository and running the local unit tests. Use Linux/WSL for the live Runta control plane and dashboard workflow.

Verify:

```bash
python3 --version
git --version
```

Python 3.10+ is required by the package metadata.

## 2. Clone

```bash
git clone https://github.com/aryansolanki/Agentic-Software-Engineering-Evaluation-Platform.git
cd Agentic-Software-Engineering-Evaluation-Platform
```

## 3. Install

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -e ".[dev]"
```

Every new shell:

```bash
cd Agentic-Software-Engineering-Evaluation-Platform
source .venv/bin/activate
```

## 4. Configure credentials

```bash
cp .env.example .env
```

Set locally:

```env
RUNTA_TOKEN=<your Runta token>
OPENAI_API_KEY=<your OpenAI key>
OPENAI_MODEL=gpt-5-mini
```

Do not commit `.env`.

The local process stores the OpenAI key as a Runta tenant secret. Candidate/judge runtimes receive an egress secret configuration for `api.openai.com` rather than the real key being intentionally copied into their normal environment.

## 5. Run local checks

```bash
pytest -q
python -m compileall -q src
```

Current repository baseline: **28 passing tests**.

## 6. Runta preflight

```bash
runta-eval preflight
```

A healthy result reports `status: ok` and `health: true`.

## 7. Start the dashboard

```bash
runta-eval serve
```

Open from your browser:

```text
http://localhost:8000
```

## 8. First end-to-end run

Use the built-in fixture first:

```text
Name: Fix calculator rounding bug
Source: Built-in controlled fixture
Candidates: 1
Evaluation: Deterministic
Test command: python3 -m unittest -v
Keep runtimes: ON
```

Confirm:

- run completes;
- candidate tests exit `0`;
- a winner is selected;
- **View diff** shows the source patch.

Then repeat with multiple candidates and Hybrid evaluation.

## 9. Public Git repository mode

Select **Public Git URL**. Supply a public HTTPS clone URL plus repository-specific setup and test commands.

Example dependency setup on Debian/Ubuntu:

```bash
python3 -m venv .venv && \
.venv/bin/python -m pip install --upgrade pip && \
.venv/bin/python -m pip install -r requirements-dev.txt
```

Example test command:

```bash
.venv/bin/python -m pytest -q
```

Add only the egress hosts needed by setup, such as:

```text
github.com,pypi.org,files.pythonhosted.org
```

## 10. Cleanup

Preview project-owned resources:

```bash
runta-eval cleanup
```

Delete them only after reviewing the list:

```bash
runta-eval cleanup --execute
```

Cleanup is scoped to project resources using the `rae-` naming convention.

## Optional Runta capability experiments

```bash
runta-eval level1
runta-eval level2 --forks 3
runta-eval level3 --workers 4
runta-eval level4
runta-eval memory-auto
runta-eval autosuspend
```

These commands exist to exercise Runta capabilities separately from the product workflow. See [docs/experiments-and-results.md](docs/experiments-and-results.md).
