# .github

Global reusable workflows and agent scripts for your GitHub org or account.

## What this repo does

When an issue in any opted-in repo is assigned and has the right labels, a GitHub Actions workflow runs an AI agent to perform the requested task.

## Access control

Workflows are gated by two secrets:

| Secret | Description |
|---|---|
| `WORKFLOW_USER` | The GitHub username/org that owns this `.github` repo (e.g. `your-org`) |
| `ALLOWED_USERS` | Comma-separated list of GitHub usernames allowed to trigger workflows (e.g. `user1,user2,user3`) |

Only users in `ALLOWED_USERS` can initiate workflows — all others are silently skipped.

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

### 1. Add five secrets to the repo

`Settings → Secrets and variables → Actions → New repository secret`

| Secret | Description |
|---|---|
| `GH_PAT` | Personal access token with `repo` scope |
| `ANTHROPIC_API_KEY` | Anthropic API key (for Claude) |
| `CONTEXT7_API_KEY` | Context7 API key (for doc lookups) |
| `WORKFLOW_USER` | GitHub username/org that owns this `.github` repo |
| `ALLOWED_USERS` | Comma-separated list of GitHub usernames allowed to trigger workflows |

### 2. Copy the example caller workflow

```bash
cp .github/workflows/on-issue-assigned.yml.example \
   <your-repo>/.github/workflows/on-issue-assigned.yml
```

Replace `WORKFLOW_USER` in the `uses:` line with your actual username/org, then commit and push.

### 3. Use it

1. Add the `agent` label **and** a task label (e.g., `refine`) to an issue
2. Assign the issue
3. The matching workflow fires automatically (if you are in `ALLOWED_USERS`)

## Agent pipeline

```
issues: assigned
  └─ if: labels 'agent' + 'refine' present AND actor in ALLOWED_USERS
       └─ refine-issue.yml (reusable)
            ├─ checkout caller repo
            ├─ checkout WORKFLOW_USER/.github (agent scripts)
            ├─ pip install anthropic requests
            └─ python scripts/refine_issue.py
                 ├─ fetch issue via GitHub API
                 ├─ search repo for relevant files
                 ├─ fetch Context7 docs for detected libraries
                 ├─ call Claude Sonnet to refine
                 └─ PATCH issue body via GitHub API
```
