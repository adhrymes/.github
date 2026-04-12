# adhrymes/.github

Global reusable workflows and agent scripts for the `adhrymes` org.

## What this repo does

When an issue in any opted-in repo is assigned and has the right labels, a GitHub Actions workflow runs an AI agent to perform the requested task.

## Label gate

Every agent-powered task requires **two labels**:

| Label | Purpose |
|---|---|
| `agent` | Enables agent processing (always required) |
| Task label | Selects which agent task to run |

### Available task labels

| Task label | What happens |
|---|---|
| `refine` | Rewrites/refines the issue — adds implementation details, enforces type prefixes (`Spike:` / `Story:` / `Epic:`), and verifies against the codebase and docs |

More task labels can be added in the future (e.g., `triage`, `estimate`).

Issues without **both** `agent` and a task label are silently skipped.

## Opting a repo in

### 1. Add three secrets to the repo

`Settings → Secrets and variables → Actions → New repository secret`

| Secret | Description |
|---|---|
| `GH_PAT` | Personal access token with `repo` scope |
| `ANTHROPIC_API_KEY` | Anthropic API key (for Claude) |
| `CONTEXT7_API_KEY` | Context7 API key (for doc lookups) |

### 2. Copy the example caller workflow

```bash
cp .github/workflows/on-issue-assigned.yml.example \
   <your-repo>/.github/workflows/on-issue-assigned.yml
```

Commit and push the file to your repo.

### 3. Use it

1. Add the `agent` label **and** a task label (e.g., `refine`) to an issue
2. Assign the issue
3. The matching workflow fires automatically

## Agent pipeline

```
issues: assigned
  └─ if: labels 'agent' + 'refine' present
       └─ refine-issue.yml (reusable)
            ├─ checkout caller repo
            ├─ checkout adhrymes/.github (agent scripts)
            ├─ pip install anthropic requests
            └─ python scripts/refine_issue.py
                 ├─ fetch issue via GitHub API
                 ├─ search repo for relevant files
                 ├─ fetch Context7 docs for detected libraries
                 ├─ call Claude Sonnet to refine
                 └─ PATCH issue body via GitHub API
```
