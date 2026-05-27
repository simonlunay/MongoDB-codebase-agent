"""
MongoDB Atlas codebase agent tools.

Environment variables consumed (read directly from os.environ — never load_dotenv):
  MONGODB_URI              — MongoDB Atlas connection string
  GITHUB_TOKEN             — GitHub personal access token
  GOOGLE_CLOUD_PROJECT     — GCP project ID for Vertex AI
  GOOGLE_CLOUD_LOCATION    — GCP region (e.g. us-central1)
"""

import os
import re
import base64
import json
from datetime import datetime, timezone
from typing import Any

import requests
from pymongo import MongoClient

# ---------------------------------------------------------------------------
# Language detection
# ---------------------------------------------------------------------------

_EXT_TO_LANG: dict[str, str] = {
    ".py": "Python",
    ".js": "JavaScript",
    ".ts": "TypeScript",
    ".jsx": "JavaScript",
    ".tsx": "TypeScript",
    ".java": "Java",
    ".go": "Go",
    ".rs": "Rust",
    ".cpp": "C++",
    ".cc": "C++",
    ".cxx": "C++",
    ".c": "C",
    ".h": "C/C++ Header",
    ".cs": "C#",
    ".rb": "Ruby",
    ".php": "PHP",
    ".swift": "Swift",
    ".kt": "Kotlin",
    ".scala": "Scala",
    ".r": "R",
    ".R": "R",
    ".sh": "Shell",
    ".bash": "Shell",
    ".zsh": "Shell",
    ".md": "Markdown",
    ".json": "JSON",
    ".yaml": "YAML",
    ".yml": "YAML",
    ".toml": "TOML",
    ".html": "HTML",
    ".css": "CSS",
    ".scss": "SCSS",
    ".sql": "SQL",
    ".xml": "XML",
    ".tf": "Terraform",
    ".dockerfile": "Dockerfile",
}

_CODE_EXTENSIONS = set(_EXT_TO_LANG.keys())

# Max bytes to embed / store per file (avoid huge files)
_MAX_FILE_BYTES = 500_000

# ---------------------------------------------------------------------------
# Lazy singletons
# ---------------------------------------------------------------------------

_mongo_client: MongoClient | None = None
_genai_client: Any = None


def _get_db():
    """Return the MongoDB database, creating the client lazily."""
    global _mongo_client
    if _mongo_client is None:
        uri = os.environ["MONGODB_URI"]
        _mongo_client = MongoClient(uri)
    return _mongo_client["codebase_db"]


def _get_genai_client():
    """Return the google.genai client configured for Vertex AI, lazily."""
    global _genai_client
    if _genai_client is None:
        import google.genai as genai  # noqa: PLC0415

        _genai_client = genai.Client(
            vertexai=True,
            project=os.environ.get("GOOGLE_CLOUD_PROJECT"),
            location=os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1"),
        )
    return _genai_client


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _generate_embedding(text: str) -> list[float]:
    """Generate a text-embedding-004 vector via Vertex AI."""
    client = _get_genai_client()
    # Truncate to ~25 000 chars to stay within token limits
    truncated = text[:25_000]
    response = client.models.embed_content(
        model="text-embedding-004",
        contents=truncated,
    )
    return list(response.embeddings[0].values)


def _parse_github_url(github_url: str) -> tuple[str, str]:
    """Return (owner, repo) from a GitHub URL."""
    url = github_url.rstrip("/")
    if url.endswith(".git"):
        url = url[:-4]
    match = re.search(r"github\.com/([^/]+)/([^/]+)", url)
    if not match:
        raise ValueError(f"Cannot parse GitHub URL: {github_url!r}")
    return match.group(1), match.group(2)


def _github_headers() -> dict[str, str]:
    token = os.environ.get("GITHUB_TOKEN", "")
    headers: dict[str, str] = {"Accept": "application/vnd.github.v3+json"}
    if token:
        headers["Authorization"] = f"token {token}"
    return headers


def _detect_language(file_path: str) -> str:
    _, ext = os.path.splitext(file_path.lower())
    # Special case for Dockerfile
    if os.path.basename(file_path).lower() == "dockerfile":
        return "Dockerfile"
    return _EXT_TO_LANG.get(ext, "Unknown")


def _normalize_repo_url(repo_url: str) -> str:
    """Canonical form used as the stored key (no trailing slash, no .git)."""
    url = repo_url.rstrip("/")
    if url.endswith(".git"):
        url = url[:-4]
    return url


# ---------------------------------------------------------------------------
# Tool 1 — index_repository
# ---------------------------------------------------------------------------

def index_repository(github_url: str) -> str:
    """
    Fetch all code files from a GitHub repository via the GitHub API,
    generate text-embedding-004 embeddings for each file, and store them
    in the MongoDB Atlas 'codebase' collection.

    Args:
        github_url: Full GitHub repository URL
                    (e.g. https://github.com/owner/repo).

    Returns:
        A summary string describing how many files were indexed.
    """
    owner, repo = _parse_github_url(github_url)
    repo_url = _normalize_repo_url(github_url)
    headers = _github_headers()

    # Fetch the full file tree (recursive)
    tree_url = f"https://api.github.com/repos/{owner}/{repo}/git/trees/HEAD?recursive=1"
    tree_resp = requests.get(tree_url, headers=headers, timeout=30)
    tree_resp.raise_for_status()
    tree_data = tree_resp.json()

    blobs = [
        item for item in tree_data.get("tree", [])
        if item.get("type") == "blob"
        and os.path.splitext(item["path"].lower())[1] in _CODE_EXTENSIONS
        or os.path.basename(item.get("path", "")).lower() == "dockerfile"
    ]

    db = _get_db()
    coll = db["codebase"]

    indexed = 0
    skipped = 0
    errors = []

    for item in blobs:
        file_path = item["path"]
        file_size = item.get("size", 0)

        if file_size > _MAX_FILE_BYTES:
            skipped += 1
            continue

        try:
            content_url = (
                f"https://api.github.com/repos/{owner}/{repo}/contents/{file_path}"
            )
            content_resp = requests.get(content_url, headers=headers, timeout=20)
            content_resp.raise_for_status()
            content_data = content_resp.json()

            raw_content = content_data.get("content", "")
            if content_data.get("encoding") == "base64":
                file_content = base64.b64decode(raw_content).decode("utf-8", errors="replace")
            else:
                file_content = raw_content

            language = _detect_language(file_path)
            embedding = _generate_embedding(file_content)

            doc = {
                "file_path": file_path,
                "content": file_content,
                "embedding": embedding,
                "repo_url": repo_url,
                "language": language,
            }

            coll.update_one(
                {"repo_url": repo_url, "file_path": file_path},
                {"$set": doc},
                upsert=True,
            )
            indexed += 1

        except Exception as exc:  # noqa: BLE001
            errors.append(f"{file_path}: {exc}")

    summary = (
        f"Indexed {indexed} files from {repo_url}. "
        f"Skipped {skipped} oversized files."
    )
    if errors:
        summary += f" Errors on {len(errors)} file(s): " + "; ".join(errors[:5])
    return summary


# ---------------------------------------------------------------------------
# Tool 2 — search_codebase
# ---------------------------------------------------------------------------

def search_codebase(query: str, repo_url: str) -> str:
    """
    Search the indexed codebase using a natural-language query via MongoDB
    Atlas Vector Search (index name: vector_index).

    Args:
        query:    Natural-language search query.
        repo_url: GitHub repository URL used when indexing.

    Returns:
        A formatted string listing the top-5 matching files and snippets.
    """
    repo_url = _normalize_repo_url(repo_url)
    query_embedding = _generate_embedding(query)

    db = _get_db()
    coll = db["codebase"]

    pipeline = [
        {
            "$vectorSearch": {
                "index": "vector_index",
                "path": "embedding",
                "queryVector": query_embedding,
                "numCandidates": 100,
                "limit": 5,
                "filter": {"repo_url": {"$eq": repo_url}},
            }
        },
        {
            "$project": {
                "_id": 0,
                "file_path": 1,
                "language": 1,
                "content": 1,
                "score": {"$meta": "vectorSearchScore"},
            }
        },
    ]

    results = list(coll.aggregate(pipeline))

    if not results:
        return f"No results found for query '{query}' in {repo_url}."

    lines = [f"Top {len(results)} results for: '{query}'\n"]
    for i, doc in enumerate(results, 1):
        snippet = doc["content"][:400].replace("\n", " ")
        lines.append(
            f"{i}. [{doc['language']}] {doc['file_path']} "
            f"(score: {doc['score']:.4f})\n   {snippet}...\n"
        )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Tool 3 — explain_code
# ---------------------------------------------------------------------------

def explain_code(repo_url: str, file_path: str) -> str:
    """
    Retrieve a file from the MongoDB codebase index and return its full
    content so the agent can provide a detailed explanation.

    Args:
        repo_url:  GitHub repository URL.
        file_path: Path to the file within the repository.

    Returns:
        The file language, path, and full content.
    """
    repo_url = _normalize_repo_url(repo_url)
    db = _get_db()
    coll = db["codebase"]

    doc = coll.find_one(
        {"repo_url": repo_url, "file_path": file_path},
        {"_id": 0, "file_path": 1, "language": 1, "content": 1},
    )
    if not doc:
        return f"File '{file_path}' not found in {repo_url}. Run index_repository first."

    return (
        f"File: {doc['file_path']}\n"
        f"Language: {doc['language']}\n"
        f"Repository: {repo_url}\n\n"
        f"```{doc['language'].lower()}\n{doc['content']}\n```"
    )


# ---------------------------------------------------------------------------
# Tool 4 — find_bugs
# ---------------------------------------------------------------------------

# Patterns that often indicate bugs or security issues
_BUG_PATTERNS = [
    (r"eval\s*\(", "Use of eval() — potential code injection risk"),
    (r"exec\s*\(", "Use of exec() — potential code injection risk"),
    (r"os\.system\s*\(", "Use of os.system() — prefer subprocess with shell=False"),
    (r"subprocess\.call\(.+shell\s*=\s*True", "subprocess with shell=True — command injection risk"),
    (r"password\s*=\s*['\"][^'\"]{1,}", "Hardcoded password literal"),
    (r"secret\s*=\s*['\"][^'\"]{1,}", "Hardcoded secret literal"),
    (r"api_key\s*=\s*['\"][^'\"]{1,}", "Hardcoded API key"),
    (r"TODO|FIXME|HACK|XXX", "Developer note flagged for follow-up"),
    (r"except\s*:", "Bare except clause — catches all exceptions including SystemExit"),
    (r"print\s*\(.+password", "Possible password leak via print/logging"),
    (r"SELECT .+ FROM .+\+", "Potential SQL injection via string concatenation"),
    (r"innerHTML\s*=", "Direct innerHTML assignment — XSS risk"),
    (r"dangerouslySetInnerHTML", "React dangerouslySetInnerHTML — XSS risk"),
    (r"Math\.random\(\)", "Math.random() not cryptographically secure"),
]


def find_bugs(repo_url: str, file_path: str) -> str:
    """
    Retrieve a file from MongoDB and perform static analysis to surface
    potential bugs and security issues.

    Args:
        repo_url:  GitHub repository URL.
        file_path: Path to the file within the repository.

    Returns:
        The file content plus a list of flagged patterns for deeper analysis.
    """
    repo_url = _normalize_repo_url(repo_url)
    db = _get_db()
    coll = db["codebase"]

    doc = coll.find_one(
        {"repo_url": repo_url, "file_path": file_path},
        {"_id": 0, "file_path": 1, "language": 1, "content": 1},
    )
    if not doc:
        return f"File '{file_path}' not found in {repo_url}. Run index_repository first."

    content = doc["content"]
    findings: list[str] = []

    for pattern, description in _BUG_PATTERNS:
        matches = list(re.finditer(pattern, content, re.IGNORECASE))
        if matches:
            line_nums = []
            for m in matches[:3]:  # report first 3 occurrences
                line_num = content[: m.start()].count("\n") + 1
                line_nums.append(str(line_num))
            findings.append(
                f"• {description} — line(s): {', '.join(line_nums)}"
            )

    findings_text = (
        "\n".join(findings) if findings else "No obvious static patterns flagged."
    )

    return (
        f"File: {doc['file_path']}\n"
        f"Language: {doc['language']}\n"
        f"Repository: {repo_url}\n\n"
        f"=== Static Analysis Findings ===\n{findings_text}\n\n"
        f"=== Full Source ===\n```{doc['language'].lower()}\n{content}\n```"
    )


# ---------------------------------------------------------------------------
# Tool 5 — create_github_issue
# ---------------------------------------------------------------------------

def create_github_issue(repo_url: str, title: str, body: str) -> str:
    """
    Create a new GitHub issue on the specified repository.

    Args:
        repo_url: GitHub repository URL (e.g. https://github.com/owner/repo).
        title:    Issue title.
        body:     Issue body (supports Markdown).

    Returns:
        URL of the created issue or an error message.
    """
    owner, repo = _parse_github_url(repo_url)
    api_url = f"https://api.github.com/repos/{owner}/{repo}/issues"

    resp = requests.post(
        api_url,
        headers=_github_headers(),
        json={"title": title, "body": body},
        timeout=20,
    )
    resp.raise_for_status()
    issue = resp.json()
    return f"Issue created: #{issue['number']} — {issue['html_url']}"


# ---------------------------------------------------------------------------
# Tool 6 — generate_documentation
# ---------------------------------------------------------------------------

def generate_documentation(repo_url: str, file_path: str) -> str:
    """
    Retrieve a file from MongoDB and return its content structured for
    markdown documentation generation.

    Args:
        repo_url:  GitHub repository URL.
        file_path: Path to the file within the repository.

    Returns:
        The file content with a documentation scaffold so the agent can
        produce Markdown docs.
    """
    repo_url = _normalize_repo_url(repo_url)
    db = _get_db()
    coll = db["codebase"]

    doc = coll.find_one(
        {"repo_url": repo_url, "file_path": file_path},
        {"_id": 0, "file_path": 1, "language": 1, "content": 1},
    )
    if not doc:
        return f"File '{file_path}' not found in {repo_url}. Run index_repository first."

    return (
        f"# Documentation Request\n\n"
        f"**Repository:** {repo_url}\n"
        f"**File:** `{doc['file_path']}`\n"
        f"**Language:** {doc['language']}\n\n"
        f"Please generate comprehensive Markdown documentation for the following source file, "
        f"including: overview, public API / exports, parameters, return values, usage examples, "
        f"and any notable implementation details.\n\n"
        f"```{doc['language'].lower()}\n{doc['content']}\n```"
    )


# ---------------------------------------------------------------------------
# Tool 7 — update_mongodb_document
# ---------------------------------------------------------------------------

def update_mongodb_document(
    collection: str,
    filter_key: str,
    filter_value: str,
    update_field: str,
    update_value: str,
) -> str:
    """
    Update a single document in any MongoDB collection within the codebase_db
    database.

    Args:
        collection:   Collection name (e.g. 'codebase').
        filter_key:   Field name to match on (e.g. 'file_path').
        filter_value: Value to match (e.g. 'src/main.py').
        update_field: Field name to set.
        update_value: New value (stored as a string).

    Returns:
        A summary of the update result.
    """
    db = _get_db()
    coll = db[collection]

    result = coll.update_one(
        {filter_key: filter_value},
        {"$set": {update_field: update_value}},
    )

    if result.matched_count == 0:
        return (
            f"No document matched {{'{filter_key}': '{filter_value}'}} "
            f"in collection '{collection}'."
        )
    return (
        f"Updated {result.modified_count} document(s) in '{collection}'. "
        f"Matched: {result.matched_count}, Modified: {result.modified_count}."
    )


# ---------------------------------------------------------------------------
# Tool 8 — add_code_comment
# ---------------------------------------------------------------------------

def add_code_comment(
    repo_url: str,
    pr_number: int,
    file_path: str,
    line_number: int,
    comment: str,
) -> str:
    """
    Add a review comment to a specific line in a GitHub pull request.

    Args:
        repo_url:    GitHub repository URL.
        pr_number:   Pull request number.
        file_path:   File path within the PR diff.
        line_number: Line number in the file to comment on.
        comment:     Comment text.

    Returns:
        URL of the posted comment or an error message.
    """
    owner, repo = _parse_github_url(repo_url)
    headers = _github_headers()

    # Fetch PR to get the latest commit SHA
    pr_resp = requests.get(
        f"https://api.github.com/repos/{owner}/{repo}/pulls/{pr_number}",
        headers=headers,
        timeout=20,
    )
    pr_resp.raise_for_status()
    pr_data = pr_resp.json()
    commit_id = pr_data["head"]["sha"]

    # Post the review comment
    comment_resp = requests.post(
        f"https://api.github.com/repos/{owner}/{repo}/pulls/{pr_number}/comments",
        headers=headers,
        json={
            "body": comment,
            "commit_id": commit_id,
            "path": file_path,
            "line": line_number,
            "side": "RIGHT",
        },
        timeout=20,
    )
    comment_resp.raise_for_status()
    data = comment_resp.json()
    return f"Comment posted: {data.get('html_url', 'OK')}"


# ---------------------------------------------------------------------------
# Tool 9 — create_pull_request
# ---------------------------------------------------------------------------

def create_pull_request(
    repo_url: str,
    title: str,
    body: str,
    head_branch: str,
) -> str:
    """
    Create a GitHub pull request from head_branch into the default base branch
    (main).

    Args:
        repo_url:    GitHub repository URL.
        title:       PR title.
        body:        PR body (supports Markdown).
        head_branch: Branch containing the proposed changes.

    Returns:
        URL of the created pull request or an error message.
    """
    owner, repo = _parse_github_url(repo_url)

    # Determine the default branch
    repo_resp = requests.get(
        f"https://api.github.com/repos/{owner}/{repo}",
        headers=_github_headers(),
        timeout=20,
    )
    repo_resp.raise_for_status()
    base_branch = repo_resp.json().get("default_branch", "main")

    pr_resp = requests.post(
        f"https://api.github.com/repos/{owner}/{repo}/pulls",
        headers=_github_headers(),
        json={
            "title": title,
            "body": body,
            "head": head_branch,
            "base": base_branch,
        },
        timeout=20,
    )
    pr_resp.raise_for_status()
    pr = pr_resp.json()
    return f"Pull request created: #{pr['number']} — {pr['html_url']}"


# ---------------------------------------------------------------------------
# Tool 10 — summarize_recent_commits
# ---------------------------------------------------------------------------

def summarize_recent_commits(repo_url: str) -> str:
    """
    Fetch the last 10 commits from a GitHub repository and return a
    structured summary.

    Args:
        repo_url: GitHub repository URL.

    Returns:
        A formatted summary of the 10 most recent commits.
    """
    owner, repo = _parse_github_url(repo_url)

    resp = requests.get(
        f"https://api.github.com/repos/{owner}/{repo}/commits?per_page=10",
        headers=_github_headers(),
        timeout=20,
    )
    resp.raise_for_status()
    commits = resp.json()

    if not commits:
        return f"No commits found for {repo_url}."

    lines = [f"Last {len(commits)} commits for {repo_url}:\n"]
    for commit in commits:
        sha = commit["sha"][:7]
        message = commit["commit"]["message"].split("\n")[0]  # first line only
        author = commit["commit"]["author"]["name"]
        date = commit["commit"]["author"]["date"][:10]
        lines.append(f"  {sha} {date} [{author}] {message}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Tool 11 — audit_dependencies
# ---------------------------------------------------------------------------

def audit_dependencies(repo_url: str) -> str:
    """
    Retrieve requirements.txt (Python) or package.json (Node.js) from the
    MongoDB index and analyse the dependency list for potentially risky or
    outdated packages.

    Args:
        repo_url: GitHub repository URL.

    Returns:
        A report of the dependencies found and any flagged concerns.
    """
    repo_url = _normalize_repo_url(repo_url)
    db = _get_db()
    coll = db["codebase"]

    # Look for common dependency files
    target_files = ["requirements.txt", "package.json", "Pipfile", "pyproject.toml"]
    results: list[dict] = []

    for fname in target_files:
        doc = coll.find_one(
            {
                "repo_url": repo_url,
                "file_path": {"$regex": f"(^|/){re.escape(fname)}$"},
            },
            {"_id": 0, "file_path": 1, "language": 1, "content": 1},
        )
        if doc:
            results.append(doc)

    if not results:
        return (
            f"No dependency files (requirements.txt, package.json, etc.) "
            f"found in {repo_url}. Run index_repository first."
        )

    # Known suspicious / commonly flagged packages (illustrative list)
    _FLAGGED_PKGS = {
        "pycrypto": "Unmaintained; use pycryptodome instead",
        "pycryptodome": "OK but verify version ≥ 3.10",
        "requests": "Pin to latest; older versions had SSL issues",
        "urllib3": "Pin to ≥ 2.x; older versions had CVEs",
        "pillow": "Frequent CVEs — keep updated",
        "django": "Security releases are frequent — stay current",
        "flask": "Keep updated for security patches",
        "lodash": "Prototype-pollution CVEs in older versions",
        "moment": "Deprecated; prefer date-fns or dayjs",
        "serialize-javascript": "XSS CVE in < 3.1",
        "node-fetch": "SSRF in older versions; prefer native fetch",
    }

    report_parts: list[str] = [f"# Dependency Audit — {repo_url}\n"]

    for doc in results:
        report_parts.append(f"## {doc['file_path']}\n")
        content = doc["content"]

        if doc["file_path"].endswith("requirements.txt"):
            pkg_lines = [
                line.strip()
                for line in content.splitlines()
                if line.strip() and not line.startswith("#")
            ]
            packages = [re.split(r"[>=<!~\[]", p)[0].strip().lower() for p in pkg_lines]
            report_parts.append("**Packages found:**\n" + "\n".join(f"- {p}" for p in pkg_lines))
            flags = [
                f"⚠ `{pkg}`: {note}"
                for pkg in packages
                for known, note in _FLAGGED_PKGS.items()
                if known == pkg
            ]
            if flags:
                report_parts.append("\n**Flagged packages:**\n" + "\n".join(flags))
            else:
                report_parts.append("\n✅ No well-known vulnerable packages detected in static list.")

        elif doc["file_path"].endswith("package.json"):
            try:
                pkg_json = json.loads(content)
                all_deps = {}
                all_deps.update(pkg_json.get("dependencies", {}))
                all_deps.update(pkg_json.get("devDependencies", {}))
                report_parts.append(
                    "**Packages found:**\n"
                    + "\n".join(f"- {k}: {v}" for k, v in all_deps.items())
                )
                flags = [
                    f"⚠ `{pkg}`: {note}"
                    for pkg in (k.lower() for k in all_deps)
                    for known, note in _FLAGGED_PKGS.items()
                    if known == pkg
                ]
                if flags:
                    report_parts.append("\n**Flagged packages:**\n" + "\n".join(flags))
                else:
                    report_parts.append("\n✅ No well-known vulnerable packages detected in static list.")
            except json.JSONDecodeError:
                report_parts.append(f"Could not parse {doc['file_path']} as JSON.")
        else:
            # For Pipfile, pyproject.toml etc. just return the raw content
            report_parts.append(f"```\n{content}\n```")

        report_parts.append("")

    return "\n".join(report_parts)


# ---------------------------------------------------------------------------
# Tool 12 — list_pull_requests
# ---------------------------------------------------------------------------

def list_pull_requests(repo_url: str, state: str = "open") -> str:
    """
    List pull requests for a GitHub repository.

    Args:
        repo_url: GitHub repository URL.
        state:    PR state filter — 'open', 'closed', or 'all'. Defaults to 'open'.

    Returns:
        A formatted list of PRs with number, title, author, date, and URL.
    """
    owner, repo = _parse_github_url(repo_url)

    if state not in ("open", "closed", "all"):
        state = "open"

    resp = requests.get(
        f"https://api.github.com/repos/{owner}/{repo}/pulls",
        headers=_github_headers(),
        params={"state": state, "per_page": 50},
        timeout=20,
    )
    resp.raise_for_status()
    prs = resp.json()

    if not prs:
        return f"No {state} pull requests found for {repo_url}."

    lines = [f"{len(prs)} {state} pull request(s) for {repo_url}:\n"]
    for pr in prs:
        created = pr["created_at"][:10]
        author = pr["user"]["login"]
        lines.append(
            f"  #{pr['number']} [{created}] {pr['title']}\n"
            f"         Author: {author} | {pr['html_url']}"
        )

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Tool 13 — review_pull_request
# ---------------------------------------------------------------------------

_DIFF_SECURITY_PATTERNS = [
    (r"^\+.*(password|secret|api_key|token)\s*=\s*['\"][^'\"]{4,}", "Possible hardcoded credential added"),
    (r"^\+.*eval\s*\(", "eval() added in diff"),
    (r"^\+.*exec\s*\(", "exec() added in diff"),
    (r"^\+.*shell\s*=\s*True", "subprocess shell=True added in diff"),
    (r"^\+.*innerHTML\s*=", "innerHTML assignment added in diff"),
    (r"^\+.*TODO|^\+.*FIXME|^\+.*HACK", "Developer note added"),
]


def review_pull_request(repo_url: str, pr_number: int) -> str:
    """
    Fetch a pull request's description, changed files, and diff from GitHub,
    then return a structured analysis with a recommended review decision.

    Args:
        repo_url:  GitHub repository URL.
        pr_number: Pull request number.

    Returns:
        A detailed report including files changed, lines added/removed,
        flagged diff patterns, and a recommendation of APPROVE,
        REQUEST_CHANGES, or COMMENT with reasoning.
    """
    owner, repo = _parse_github_url(repo_url)
    headers = _github_headers()

    # PR metadata
    pr_resp = requests.get(
        f"https://api.github.com/repos/{owner}/{repo}/pulls/{pr_number}",
        headers=headers,
        timeout=20,
    )
    pr_resp.raise_for_status()
    pr = pr_resp.json()

    # Changed files
    files_resp = requests.get(
        f"https://api.github.com/repos/{owner}/{repo}/pulls/{pr_number}/files",
        headers=headers,
        params={"per_page": 100},
        timeout=20,
    )
    files_resp.raise_for_status()
    files = files_resp.json()

    # Raw diff
    diff_headers = {**headers, "Accept": "application/vnd.github.v3.diff"}
    diff_resp = requests.get(
        f"https://api.github.com/repos/{owner}/{repo}/pulls/{pr_number}",
        headers=diff_headers,
        timeout=30,
    )
    diff_resp.raise_for_status()
    diff_text = diff_resp.text[:20_000]  # cap to avoid huge diffs

    # Aggregate stats
    total_additions = sum(f.get("additions", 0) for f in files)
    total_deletions = sum(f.get("deletions", 0) for f in files)

    # File list
    file_lines = []
    for f in files:
        status = f.get("status", "modified")
        additions = f.get("additions", 0)
        deletions = f.get("deletions", 0)
        file_lines.append(
            f"  [{status}] {f['filename']}  +{additions}/-{deletions}"
        )

    # Static pattern scan on diff
    diff_flags: list[str] = []
    for pattern, description in _DIFF_SECURITY_PATTERNS:
        if re.search(pattern, diff_text, re.IGNORECASE | re.MULTILINE):
            diff_flags.append(f"  ⚠ {description}")

    # Heuristic signals
    concerns: list[str] = []
    if diff_flags:
        for flag in diff_flags:
            concerns.append(flag.strip())
    if len(files) > 30:
        concerns.append(f"Large PR: {len(files)} files changed — consider splitting into smaller PRs")
    if total_additions > 500:
        concerns.append(f"High line count: +{total_additions} additions across {len(files)} files")

    # Derive a concrete recommended action from the heuristics
    if diff_flags:
        recommended_action = "REQUEST_CHANGES"
        recommendation_reason = (
            "Security-sensitive patterns were detected in the diff (see flags above). "
            "These must be addressed before merging."
        )
    elif concerns:
        recommended_action = "COMMENT"
        recommendation_reason = (
            "No security issues were detected, but the PR has structural concerns "
            "(size or complexity) that warrant discussion before approval."
        )
    else:
        recommended_action = "APPROVE"
        recommendation_reason = (
            "No security flags or structural concerns were detected by static analysis. "
            "The diff appears clean. Manual review of logic correctness is still advised."
        )

    flags_text = "\n".join(f"  {f}" for f in diff_flags) if diff_flags else "  None detected"
    concerns_text = "\n".join(f"  - {c}" for c in concerns) if concerns else "  None"

    return (
        f"# PR Review Analysis: #{pr_number} - {pr['title']}\n\n"
        f"**Author:** {pr['user']['login']}\n"
        f"**Branch:** `{pr['head']['ref']}` -> `{pr['base']['ref']}`\n"
        f"**State:** {pr['state']}\n"
        f"**Created:** {pr['created_at'][:10]}\n"
        f"**URL:** {pr['html_url']}\n\n"
        f"## Description\n{pr.get('body') or '(no description)'}\n\n"
        f"## Files Changed ({len(files)} files, +{total_additions}/-{total_deletions})\n"
        + "\n".join(file_lines) + "\n\n"
        f"## Security Pattern Flags\n{flags_text}\n\n"
        f"## Concerns\n{concerns_text}\n\n"
        f"## Diff (first 20 000 chars)\n```diff\n{diff_text}\n```\n\n"
        f"---\n\n"
        f"## Recommended Action: {recommended_action}\n\n"
        f"**Reasoning:** {recommendation_reason}\n\n"
        f"> This analysis has NOT been submitted to GitHub. "
        f"Present this recommendation to the user and ask for explicit confirmation "
        f"before calling submit_pr_review."
    )


# ---------------------------------------------------------------------------
# Tool 14 — submit_pr_review
# ---------------------------------------------------------------------------

_VALID_REVIEW_EVENTS = {"APPROVE", "REQUEST_CHANGES", "COMMENT"}


def submit_pr_review(
    repo_url: str,
    pr_number: int,
    event: str,
    comment: str,
) -> str:
    """
    Submit a review on a GitHub pull request.

    Args:
        repo_url:  GitHub repository URL.
        pr_number: Pull request number.
        event:     Review decision — must be 'APPROVE', 'REQUEST_CHANGES',
                   or 'COMMENT'.
        comment:   Review body text.

    Returns:
        Confirmation with the review ID and HTML URL.
    """
    event = event.upper()
    if event not in _VALID_REVIEW_EVENTS:
        return (
            f"Invalid event '{event}'. Must be one of: "
            + ", ".join(sorted(_VALID_REVIEW_EVENTS))
        )

    owner, repo = _parse_github_url(repo_url)

    resp = requests.post(
        f"https://api.github.com/repos/{owner}/{repo}/pulls/{pr_number}/reviews",
        headers=_github_headers(),
        json={"body": comment, "event": event},
        timeout=20,
    )
    resp.raise_for_status()
    review = resp.json()
    return (
        f"Review submitted: {event} on PR #{pr_number}. "
        f"Review ID: {review['id']} | {review.get('html_url', '')}"
    )


# ---------------------------------------------------------------------------
# Tool 15 — merge_pull_request
# ---------------------------------------------------------------------------

_VALID_MERGE_METHODS = {"merge", "squash", "rebase"}


def merge_pull_request(
    repo_url: str,
    pr_number: int,
    merge_method: str = "squash",
) -> str:
    """
    Merge a GitHub pull request.

    Args:
        repo_url:     GitHub repository URL.
        pr_number:    Pull request number.
        merge_method: How to merge — 'squash', 'merge', or 'rebase'.
                      Defaults to 'squash'.

    Returns:
        Confirmation message with the resulting merge commit SHA.
    """
    if merge_method not in _VALID_MERGE_METHODS:
        merge_method = "squash"

    owner, repo = _parse_github_url(repo_url)

    resp = requests.put(
        f"https://api.github.com/repos/{owner}/{repo}/pulls/{pr_number}/merge",
        headers=_github_headers(),
        json={"merge_method": merge_method},
        timeout=20,
    )
    resp.raise_for_status()
    result = resp.json()
    sha = result.get("sha", "unknown")
    return (
        f"PR #{pr_number} merged via '{merge_method}'. "
        f"Merge commit SHA: {sha[:7]}. {result.get('message', '')}"
    )


# ---------------------------------------------------------------------------
# Tool 16 — log_pr_review
# ---------------------------------------------------------------------------

def log_pr_review(
    repo_url: str,
    pr_number: int,
    decision: str,
    reasoning: str,
) -> str:
    """
    Persist a PR review decision and its reasoning to the MongoDB
    'pr_reviews' collection in codebase_db.

    Args:
        repo_url:  GitHub repository URL.
        pr_number: Pull request number.
        decision:  Review decision (e.g. 'APPROVE', 'REQUEST_CHANGES', 'COMMENT').
        reasoning: Detailed reasoning behind the decision.

    Returns:
        Confirmation that the review log was stored, including its document ID.
    """
    repo_url = _normalize_repo_url(repo_url)
    db = _get_db()
    coll = db["pr_reviews"]

    doc = {
        "repo_url": repo_url,
        "pr_number": pr_number,
        "decision": decision.upper(),
        "reasoning": reasoning,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    result = coll.insert_one(doc)
    return (
        f"PR review logged. Collection: pr_reviews | "
        f"Document ID: {result.inserted_id} | "
        f"PR #{pr_number} | Decision: {doc['decision']}"
    )
