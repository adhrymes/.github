"""Refine a GitHub issue using Claude Sonnet and Context7 documentation.

This script:
1. Fetches the issue from the GitHub API
2. Detects the issue type (Spike/Story/Epic)
3. Searches for relevant codebase files
4. Fetches Context7 docs for detected libraries
5. Detects the epic parent issue if present
6. Calls Claude Sonnet to refine the issue
7. Applies the changes back via the GitHub API
"""

from __future__ import annotations

import base64
import json
import os
import re
import sys
from typing import Any

import anthropic
import requests

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

GITHUB_API = "https://api.github.com"
CONTEXT7_API = "https://context7.com/api/v1"

# Known stack for adhrymes/jis_foot_massage_site
KNOWN_STACKS: dict[str, list[str]] = {
    "adhrymes/jis_foot_massage_site": [
        "fastapi",
        "jinja2",
        "sqlmodel",
        "alpinejs",
        "htmx",
        "tailwindcss",
    ],
}

# Label definitions: name -> (color, description)
TYPE_LABELS: dict[str, tuple[str, str]] = {
    "spike": ("#fbca04", "A time-boxed investigation or research task"),
    "story": ("#0075ca", "A user-facing feature or improvement"),
    "epic": ("#7057ff", "A large body of work made up of stories and spikes"),
}

ISSUE_TYPE_PREFIXES: dict[str, str] = {
    "spike": "Spike:",
    "story": "Story:",
    "epic": "Epic:",
}

MAX_FILES = 5
MAX_FILE_LINES = 150
MAX_DOCS_CHARS = 2000
MAX_LIBRARIES = 3
CLAUDE_MODEL = "claude-sonnet-4-5"
CLAUDE_MAX_TOKENS = 4096


# ---------------------------------------------------------------------------
# GitHub helpers
# ---------------------------------------------------------------------------


def gh_headers(pat: str) -> dict[str, str]:
    """Return standard GitHub API headers."""
    return {
        "Authorization": f"token {pat}",
        "Accept": "application/vnd.github.v3+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def fetch_issue(repo: str, issue_number: int, pat: str) -> dict[str, Any]:
    """Fetch issue details from the GitHub API."""
    url = f"{GITHUB_API}/repos/{repo}/issues/{issue_number}"
    response = requests.get(url, headers=gh_headers(pat), timeout=30)
    if not response.ok:
        print(f"[ERROR] Failed to fetch issue #{issue_number}: {response.status_code} {response.text}")
        sys.exit(1)
    return response.json()  # type: ignore[no-any-return]


def search_code(repo: str, query: str, pat: str) -> list[dict[str, Any]]:
    """Search for code in a repo using the GitHub Search API."""
    url = f"{GITHUB_API}/search/code"
    params = {"q": f"{query} repo:{repo}", "per_page": MAX_FILES}
    response = requests.get(url, headers=gh_headers(pat), params=params, timeout=30)
    if not response.ok:
        print(f"[WARN] Code search failed for query '{query}': {response.status_code}")
        return []
    data = response.json()
    return data.get("items", [])  # type: ignore[no-any-return]


def fetch_file_content(repo: str, file_path: str, pat: str) -> str:
    """Fetch raw file content from GitHub, truncated to MAX_FILE_LINES lines."""
    url = f"{GITHUB_API}/repos/{repo}/contents/{file_path}"
    response = requests.get(url, headers=gh_headers(pat), timeout=30)
    if not response.ok:
        print(f"[WARN] Could not fetch file '{file_path}': {response.status_code}")
        return ""
    data = response.json()
    # GitHub returns base64-encoded content
    try:
        content = base64.b64decode(data.get("content", "")).decode("utf-8", errors="replace")
    except Exception as exc:  # noqa: BLE001
        print(f"[WARN] Could not decode '{file_path}': {exc}")
        return ""
    lines = content.splitlines()
    if len(lines) > MAX_FILE_LINES:
        lines = lines[:MAX_FILE_LINES]
        lines.append(f"... (truncated at {MAX_FILE_LINES} lines)")
    return "\n".join(lines)


def fetch_issue_labels(repo: str, issue_number: int, pat: str) -> list[str]:
    """Return label names for a given issue."""
    url = f"{GITHUB_API}/repos/{repo}/issues/{issue_number}/labels"
    response = requests.get(url, headers=gh_headers(pat), timeout=30)
    if not response.ok:
        return []
    return [label["name"] for label in response.json()]


def ensure_label_exists(repo: str, name: str, color: str, description: str, pat: str) -> None:
    """Create the label if it doesn't already exist."""
    url = f"{GITHUB_API}/repos/{repo}/labels/{name}"
    response = requests.get(url, headers=gh_headers(pat), timeout=30)
    if response.status_code == 200:
        return  # already exists
    # Create it
    create_url = f"{GITHUB_API}/repos/{repo}/labels"
    payload = {"name": name, "color": color.lstrip("#"), "description": description}
    create_response = requests.post(create_url, headers=gh_headers(pat), json=payload, timeout=30)
    if create_response.ok:
        print(f"[INFO] Created label '{name}'")
    else:
        print(f"[WARN] Could not create label '{name}': {create_response.status_code} {create_response.text}")


def update_issue_labels(
    repo: str,
    issue_number: int,
    current_labels: list[str],
    issue_type: str,
    pat: str,
) -> None:
    """Remove conflicting type labels and add the correct one."""
    if issue_type not in TYPE_LABELS:
        return

    color, description = TYPE_LABELS[issue_type]
    ensure_label_exists(repo, issue_type, color, description, pat)

    # Remove conflicting type labels
    labels_to_keep = [
        lbl for lbl in current_labels if lbl not in TYPE_LABELS or lbl == issue_type
    ]
    if issue_type not in labels_to_keep:
        labels_to_keep.append(issue_type)

    url = f"{GITHUB_API}/repos/{repo}/issues/{issue_number}"
    response = requests.patch(
        url,
        headers=gh_headers(pat),
        json={"labels": labels_to_keep},
        timeout=30,
    )
    if response.ok:
        print(f"[INFO] Updated labels: {labels_to_keep}")
    else:
        print(f"[WARN] Could not update labels: {response.status_code} {response.text}")


def update_issue(
    repo: str,
    issue_number: int,
    title: str,
    body: str,
    pat: str,
) -> None:
    """Update the issue title and body via the GitHub API."""
    url = f"{GITHUB_API}/repos/{repo}/issues/{issue_number}"
    response = requests.patch(
        url,
        headers=gh_headers(pat),
        json={"title": title, "body": body},
        timeout=30,
    )
    if response.ok:
        print(f"[INFO] Updated issue #{issue_number}")
    else:
        print(f"[ERROR] Failed to update issue: {response.status_code} {response.text}")
        sys.exit(1)


def set_parent_issue(
    repo: str,
    epic_number: int,
    sub_issue_id: int,
    pat: str,
) -> None:
    """Link a sub-issue to its epic parent via the GitHub sub-issues API."""
    url = f"{GITHUB_API}/repos/{repo}/issues/{epic_number}/sub_issues"
    response = requests.post(
        url,
        headers=gh_headers(pat),
        json={"sub_issue_id": sub_issue_id},
        timeout=30,
    )
    if response.ok:
        print(f"[INFO] Set parent issue #{epic_number} for sub-issue ID {sub_issue_id}")
    else:
        print(f"[WARN] Could not set parent issue: {response.status_code} {response.text}")


# ---------------------------------------------------------------------------
# Issue type detection
# ---------------------------------------------------------------------------


def detect_issue_type(title: str) -> str:
    """Detect issue type from the title prefix."""
    lower = title.lower().strip()
    for issue_type, prefix in ISSUE_TYPE_PREFIXES.items():
        if lower.startswith(prefix.lower()):
            return issue_type
    return "unknown"


# ---------------------------------------------------------------------------
# Epic parent detection
# ---------------------------------------------------------------------------


def detect_epic_parent(repo: str, issue_body: str, pat: str) -> int | None:
    """Scan the issue body for references to epic issues.

    Looks for patterns like:
    - Part of #123
    - Related to #123
    - Epic: #123
    - closes #123
    - #123
    """
    patterns = [
        r"(?i)part\s+of\s+#(\d+)",
        r"(?i)related\s+to\s+#(\d+)",
        r"(?i)epic\s*:\s*#(\d+)",
        r"(?i)closes?\s+#(\d+)",
        r"(?i)fixes?\s+#(\d+)",
        r"#(\d+)",
    ]
    candidate_numbers: list[int] = []
    for pattern in patterns:
        for match in re.finditer(pattern, issue_body):
            num = int(match.group(1))
            if num not in candidate_numbers:
                candidate_numbers.append(num)

    for num in candidate_numbers:
        labels = fetch_issue_labels(repo, num, pat)
        if "epic" in labels:
            print(f"[INFO] Found epic parent: #{num}")
            return num
    return None


# ---------------------------------------------------------------------------
# File search and content fetching
# ---------------------------------------------------------------------------


def extract_search_terms(issue_body: str) -> list[str]:
    """Extract key terms from the issue body for code searching."""
    # Look for file paths (containing / or .)
    file_paths = re.findall(r"\b[\w/]+\.\w+\b", issue_body)
    # Look for PascalCase (class names)
    class_names = re.findall(r"\b[A-Z][a-zA-Z0-9]{2,}\b", issue_body)
    # Look for snake_case identifiers (must contain underscore or be 6+ chars to avoid common words)
    func_names = [
        m for m in re.findall(r"\b[a-z][a-z0-9_]{4,}\b", issue_body)
        if "_" in m or len(m) >= 6
    ]
    # Combine, deduplicate, prefer shorter/more specific terms
    terms: list[str] = []
    seen: set[str] = set()
    for term in file_paths + class_names + func_names[:10]:
        if term not in seen and len(term) > 3:
            seen.add(term)
            terms.append(term)
    return terms[:5]


def find_relevant_files(
    repo: str,
    issue_body: str,
    pat: str,
) -> list[tuple[str, str]]:
    """Find and return (path, content) tuples for the most relevant files."""
    # First, look for explicitly mentioned file paths
    explicit_files = re.findall(r"`([^`]+\.[a-zA-Z]+)`", issue_body)
    explicit_files += re.findall(r"\b([\w/]+\.(?:py|js|ts|html|css|yaml|yml|json|md))\b", issue_body)

    file_paths: list[str] = []
    seen_paths: set[str] = set()

    if explicit_files:
        for fpath in explicit_files:
            if fpath not in seen_paths:
                seen_paths.add(fpath)
                file_paths.append(fpath)
        print(f"[INFO] Explicit files found in issue body: {file_paths}")
    else:
        # Search using extracted key terms
        search_terms = extract_search_terms(issue_body)
        print(f"[INFO] No explicit files; searching for terms: {search_terms}")
        for term in search_terms:
            items = search_code(repo, term, pat)
            for item in items:
                path = item.get("path", "")
                if path and path not in seen_paths:
                    seen_paths.add(path)
                    file_paths.append(path)
            if len(file_paths) >= MAX_FILES:
                break

    # Fetch content for up to MAX_FILES files
    results: list[tuple[str, str]] = []
    for fpath in file_paths[:MAX_FILES]:
        content = fetch_file_content(repo, fpath, pat)
        if content:
            results.append((fpath, content))
            print(f"[INFO] Fetched file: {fpath} ({len(content)} chars)")

    return results


# ---------------------------------------------------------------------------
# Library detection
# ---------------------------------------------------------------------------


def detect_libraries(
    repo: str,
    file_contents: list[tuple[str, str]],
    issue_body: str,
) -> list[str]:
    """Detect libraries from file imports and the issue body."""
    if repo in KNOWN_STACKS:
        print(f"[INFO] Using known stack for {repo}: {KNOWN_STACKS[repo]}")
        return KNOWN_STACKS[repo]

    libraries: set[str] = set()
    all_text = issue_body + "\n".join(content for _, content in file_contents)

    # Python imports
    for match in re.finditer(r"^\s*(?:import|from)\s+([\w.]+)", all_text, re.MULTILINE):
        lib = match.group(1).split(".")[0].lower()
        libraries.add(lib)

    # JS/TS imports
    for match in re.finditer(r"""(?:import|require)\s*\(?['"](.[^'"]+)['"]\)?""", all_text):
        lib = match.group(1).lstrip("@").split("/")[0].lower()
        libraries.add(lib)

    # Framework name mentions
    known_frameworks = [
        "fastapi", "django", "flask", "sqlalchemy", "sqlmodel",
        "pydantic", "jinja2", "htmx", "alpinejs", "tailwind",
        "react", "vue", "svelte", "nextjs", "nuxt", "express",
        "prisma", "mongoose",
    ]
    lower_text = all_text.lower()
    for fw in known_frameworks:
        if fw in lower_text:
            libraries.add(fw)

    # Exclude stdlib / noise
    stdlib_noise = {"os", "sys", "re", "json", "typing", "pathlib", "datetime", "collections"}
    libraries -= stdlib_noise

    result = sorted(libraries)[:MAX_LIBRARIES]
    print(f"[INFO] Detected libraries: {result}")
    return result


# ---------------------------------------------------------------------------
# Context7 integration
# ---------------------------------------------------------------------------


def fetch_context7_docs(library_name: str, context7_key: str) -> str:
    """Fetch documentation snippets for a library from Context7."""
    try:
        search_url = f"{CONTEXT7_API}/search"
        search_resp = requests.get(
            search_url,
            headers={"Authorization": f"Bearer {context7_key}"},
            params={"query": library_name},
            timeout=15,
        )
        if not search_resp.ok:
            print(f"[WARN] Context7 search failed for '{library_name}': {search_resp.status_code}")
            return ""

        search_data = search_resp.json()
        results = search_data.get("results", [])
        if not results:
            print(f"[WARN] No Context7 results for '{library_name}'")
            return ""

        library_id = results[0].get("id", "")
        if not library_id:
            print(f"[WARN] No Context7 ID for '{library_name}'")
            return ""

        docs_url = f"{CONTEXT7_API}/libraries/{library_id}/docs"
        docs_resp = requests.get(
            docs_url,
            headers={"Authorization": f"Bearer {context7_key}"},
            timeout=15,
        )
        if not docs_resp.ok:
            print(f"[WARN] Context7 docs fetch failed for '{library_name}': {docs_resp.status_code}")
            return ""

        docs_data = docs_resp.json()
        # Try to extract text content from the response
        content = docs_data.get("content", "") or docs_data.get("text", "") or str(docs_data)
        truncated = content[:MAX_DOCS_CHARS]
        print(f"[INFO] Fetched Context7 docs for '{library_name}' ({len(truncated)} chars)")
        return truncated

    except Exception as exc:  # noqa: BLE001
        print(f"[WARN] Context7 error for '{library_name}': {exc}")
        return ""


def fetch_all_docs(libraries: list[str], context7_key: str) -> str:
    """Fetch and concatenate docs for the top libraries."""
    parts: list[str] = []
    for lib in libraries[:MAX_LIBRARIES]:
        docs = fetch_context7_docs(lib, context7_key)
        if docs:
            parts.append(f"### {lib}\n{docs}")
    return "\n\n".join(parts) if parts else "No documentation available."


# ---------------------------------------------------------------------------
# Claude integration
# ---------------------------------------------------------------------------


def build_prompt(
    issue_type: str,
    title: str,
    body: str,
    file_contents: list[tuple[str, str]],
    docs: str,
) -> str:
    """Build the Claude prompt for issue refinement."""
    files_section = ""
    if file_contents:
        parts = [f"**{path}**\n```\n{content}\n```" for path, content in file_contents]
        files_section = "\n\n".join(parts)
    else:
        files_section = "No relevant files found."

    return f"""You are a senior software engineer refining a GitHub issue. Your job is to:
1. Ensure the title has the correct prefix (Spike:/Story:/Epic:) matching the issue type detected
2. Identify and correct any inaccurate file paths, line numbers, class names, or implementation details based on the actual codebase files provided
3. Enhance the description with accurate technical context from the codebase and library docs
4. Ensure the issue follows best practices for the tech stack
5. Preserve the original intent and structure

Issue type detected: {issue_type}
Current title: {title}
Current body: {body}

Relevant codebase files:
{files_section}

Library documentation:
{docs}

Return a JSON object with exactly these keys:
{{
  "title": "refined title with correct prefix",
  "body": "refined markdown body",
  "issue_type": "spike|story|epic|unknown"
}}

Return ONLY the JSON object, no other text."""


def call_claude(prompt: str, api_key: str) -> dict[str, Any]:
    """Call Claude Sonnet and return the parsed JSON response."""
    client = anthropic.Anthropic(api_key=api_key)
    message = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=CLAUDE_MAX_TOKENS,
        messages=[{"role": "user", "content": prompt}],
    )
    raw_text = message.content[0].text.strip()
    print(f"[INFO] Claude response received ({len(raw_text)} chars)")

    # Strip markdown code fences if present
    if raw_text.startswith("```"):
        raw_text = re.sub(r"^```(?:json)?\s*", "", raw_text)
        raw_text = re.sub(r"\s*```$", "", raw_text)

    try:
        return json.loads(raw_text)  # type: ignore[no-any-return]
    except json.JSONDecodeError as exc:
        print(f"[ERROR] Claude returned malformed JSON: {exc}")
        print(f"[ERROR] Raw response:\n{raw_text}")
        sys.exit(1)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    """Entry point: refine a GitHub issue using Claude + Context7."""
    # Load environment variables
    issue_number_str = os.environ.get("ISSUE_NUMBER", "")
    repo = os.environ.get("REPO", "")
    pat = os.environ.get("GH_PAT", "")
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY", "")
    context7_key = os.environ.get("CONTEXT7_API_KEY", "")

    if not all([issue_number_str, repo, pat, anthropic_key, context7_key]):
        print("[ERROR] Missing required environment variables: ISSUE_NUMBER, REPO, GH_PAT, ANTHROPIC_API_KEY, CONTEXT7_API_KEY")
        sys.exit(1)

    try:
        issue_number = int(issue_number_str)
    except ValueError:
        print(f"[ERROR] ISSUE_NUMBER must be an integer, got: {issue_number_str!r}")
        sys.exit(1)

    print(f"[INFO] Processing issue #{issue_number} in {repo}")

    # 1. Fetch the issue
    issue = fetch_issue(repo, issue_number, pat)
    title: str = issue.get("title", "")
    body: str = issue.get("body", "") or ""
    current_labels: list[str] = [lbl["name"] for lbl in issue.get("labels", [])]
    issue_id: int = issue["id"]
    print(f"[INFO] Issue title: {title!r}")

    # 2. Detect issue type
    issue_type = detect_issue_type(title)
    print(f"[INFO] Detected issue type: {issue_type}")

    # 3. Find relevant files
    file_contents = find_relevant_files(repo, body, pat)

    # 4. Detect libraries
    libraries = detect_libraries(repo, file_contents, body)

    # 5. Fetch Context7 docs
    docs = fetch_all_docs(libraries, context7_key)

    # 6. Detect epic parent (only relevant for stories)
    epic_number: int | None = None
    if issue_type in ("story", "unknown"):
        epic_number = detect_epic_parent(repo, body, pat)

    # 7. Build prompt and call Claude
    prompt = build_prompt(issue_type, title, body, file_contents, docs)
    print("[INFO] Calling Claude Sonnet…")
    refined = call_claude(prompt, anthropic_key)

    refined_title: str = refined.get("title", title)
    refined_body: str = refined.get("body", body)
    refined_type: str = refined.get("issue_type", issue_type)

    print(f"[INFO] Refined title: {refined_title!r}")
    print(f"[INFO] Refined issue type: {refined_type}")

    # 8. Apply changes
    update_issue(repo, issue_number, refined_title, refined_body, pat)
    update_issue_labels(repo, issue_number, current_labels, refined_type, pat)

    # 9. Set parent epic if applicable
    if refined_type == "story" and epic_number is not None:
        set_parent_issue(repo, epic_number, issue_id, pat)

    print("[INFO] Done.")


if __name__ == "__main__":
    main()
