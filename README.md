# adhrymes/.github

Global reusable workflows and agent scripts for the `adhrymes` org.

## What this repo does

When an issue in any opted-in repo is assigned **and** has the `agent` label, a GitHub Actions workflow automatically:

1. Fetches the issue title and body
2. Checks out the caller repo and searches for relevant files
3. Looks up library docs via Context7
4. Calls Claude (Sonnet) to refine the issue — correcting details, adding implementation context, and enforcing type prefixes (`Spike:` / `Story:` / `Epic:`)
5. Updates the issue body in place with the refined version

## Label gate

Issues **must** have the `agent` label to trigger refinement. Issues without it are silently skipped, so normal self-assignments are unaffected.

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

That's it. Commit and push the file to your repo.

### 3. Use it

1. Add the `agent` label to an issue
2. Assign the issue (to yourself or anyone)
3. The refinement workflow fires automatically

## Agent pipeline

```
issues: assigned
  └─ if: label 'agent' present
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
