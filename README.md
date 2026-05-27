# MongoDB Codebase Intelligence Agent

An autonomous AI agent that indexes GitHub repositories into **MongoDB Atlas Vector Search**, then lets you search, analyse, and act on any codebase using natural language. Built with **Google ADK 2.0** and **Gemini 2.5 Flash** on Vertex AI.

---

## Features

16 built-in tools covering the full development workflow:

| # | Tool | What it does |
|---|---|---|
| 1 | `index_repository` | Fetches all code files from a GitHub repo via the API, generates `text-embedding-004` embeddings, and stores them in MongoDB Atlas |
| 2 | `search_codebase` | Semantic search across an indexed repo using Atlas Vector Search |
| 3 | `explain_code` | Retrieves a file and returns a detailed explanation |
| 4 | `find_bugs` | Static analysis + LLM review for bugs and security issues |
| 5 | `generate_documentation` | Generates Markdown docs for any indexed file |
| 6 | `audit_dependencies` | Parses `requirements.txt` / `package.json` and flags risky packages |
| 7 | `summarize_recent_commits` | Fetches and summarises the last 10 commits |
| 8 | `create_github_issue` | Creates a real GitHub issue via the API |
| 9 | `create_pull_request` | Opens a GitHub pull request |
| 10 | `add_code_comment` | Posts an inline review comment on a PR |
| 11 | `update_mongodb_document` | Directly updates any document in MongoDB |
| 12 | `list_pull_requests` | Lists open, closed, or all PRs for a repo |
| 13 | `review_pull_request` | Fetches the diff, analyses it, and returns a recommended APPROVE / REQUEST_CHANGES / COMMENT decision with reasoning — does **not** submit automatically |
| 14 | `submit_pr_review` | Submits a review to GitHub after explicit user confirmation |
| 15 | `merge_pull_request` | Merges a PR using squash, merge, or rebase |
| 16 | `log_pr_review` | Persists the review decision and reasoning to MongoDB (`pr_reviews` collection) |

Plus full MongoDB Atlas access via the **MongoDB MCP Server** (Streamable HTTP transport).

> **Human-in-the-loop:** `review_pull_request` analyses and recommends but never submits. The agent always presents the analysis and asks for your explicit confirmation before calling `submit_pr_review` or `merge_pull_request`.

---

## Architecture

```
┌─────────────────────────────────────────┐
│           ADK Web UI  (:8080)           │
└────────────────┬────────────────────────┘
                 │
     ┌───────────▼───────────┐
     │   Gemini 2.5 Flash    │  (Vertex AI)
     └───────────┬───────────┘
                 │ tool calls
      ┌──────────┴──────────────────┐
      │                             │
┌─────▼──────┐          ┌──────────▼──────────┐
│ Python     │          │ MongoDB MCP Server   │
│ tools.py   │          │ (http transport)     │
│ (16 tools) │          │ localhost:3000/mcp   │
└─────┬──────┘          └──────────┬──────────┘
      │                            │
      │          ┌─────────────────┘
      │          │
┌─────▼──────────▼────────────────┐
│       MongoDB Atlas (Flex+)      │
│  • codebase   (vector search)    │
│  • pr_reviews (audit log)        │
│  • vector_index (768-dim cosine) │
└──────────────────────────────────┘
      │
┌─────▼──────────────┐
│   GitHub API v3    │
│  files / issues /  │
│  PRs / commits     │
└────────────────────┘
```

---

## Tech Stack

| Component | Technology |
|---|---|
| Agent framework | [Google ADK 2.0](https://google.github.io/adk-docs/) |
| LLM | Gemini 2.5 Flash (Vertex AI) |
| Embeddings | `text-embedding-004` — 768 dimensions (Vertex AI) |
| Vector database | MongoDB Atlas Vector Search |
| MCP integration | `mongodb-mcp-server` — http transport |
| MongoDB client | pymongo |
| GitHub integration | GitHub REST API v3 |
| Runtime | Python 3.11 |

---

## Prerequisites

- **Python 3.11+**
- **Node.js 18+** and `npm` (to run the MongoDB MCP server)
- **MongoDB Atlas cluster on Flex tier or higher** — Vector Search requires at least the Flex tier. The free M0 cluster does not support it.
- **Google Cloud project** with the Vertex AI API enabled and application default credentials configured
- **GitHub Personal Access Token** with `repo` scope — [create one here](https://github.com/settings/tokens)
- **MongoDB Atlas API key** (public/private key pair) — [create one here](https://www.mongodb.com/docs/atlas/configure-api-access/)

---

## MongoDB Atlas Setup

### Cluster tier

> **Atlas Flex tier required.** MongoDB Vector Search is not available on the free M0 shared cluster. You must use the Flex tier or a dedicated cluster (M10+).

### Create the Vector Search index

After your cluster is running, go to **Atlas UI → your cluster → Search → Create Search Index → JSON Editor**, select the `codebase_db.codebase` collection, paste the definition below, and name the index **`vector_index`**:

```json
{
  "fields": [
    {
      "type": "vector",
      "path": "embedding",
      "numDimensions": 768,
      "similarity": "cosine"
    },
    {
      "type": "filter",
      "path": "repo_url"
    }
  ]
}
```

`text-embedding-004` produces 768-dimensional vectors. The `repo_url` filter field lets searches be scoped to a single repository.

### Collections (auto-created)

| Collection | Created by | Purpose |
|---|---|---|
| `codebase` | `index_repository` | Stores file content, embeddings, and metadata |
| `pr_reviews` | `log_pr_review` | Audit log of agent review decisions |

---

## Setup

### 1. Clone the repository

```bash
git clone https://github.com/your-org/mongodb-codebase-agent.git
cd mongodb-codebase-agent
```

### 2. Create and activate a virtual environment

```bash
python -m venv venv

# Windows
venv\Scripts\activate

# macOS / Linux
source venv/bin/activate
```

### 3. Install Python dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure environment variables

Create a `.env` file in the project root (it is git-ignored):

```env
# MongoDB Atlas connection string
MONGODB_URI=mongodb+srv://<user>:<password>@<cluster>.mongodb.net/?appName=<appName>

# Google Cloud / Vertex AI
GOOGLE_CLOUD_PROJECT=your-gcp-project-id
GOOGLE_CLOUD_LOCATION=us-central1
GOOGLE_GENAI_USE_VERTEXAI=1

# GitHub Personal Access Token (repo scope)
GITHUB_TOKEN=ghp_...

# MongoDB Atlas API key (for the MCP server)
MONGODB_CLIENT_ID=your-atlas-api-public-key
MONGODB_CLIENT_SECRET=your-atlas-api-private-key
```

Then export them into your shell session before running anything:

```bash
# Windows PowerShell
$env:MONGODB_URI = "mongodb+srv://..."
$env:GOOGLE_CLOUD_PROJECT = "your-project"
$env:GOOGLE_CLOUD_LOCATION = "us-central1"
$env:GOOGLE_GENAI_USE_VERTEXAI = "1"
$env:GITHUB_TOKEN = "ghp_..."
$env:MONGODB_CLIENT_ID = "..."
$env:MONGODB_CLIENT_SECRET = "..."

# macOS / Linux
export MONGODB_URI="mongodb+srv://..."
export GOOGLE_CLOUD_PROJECT="your-project"
export GOOGLE_CLOUD_LOCATION="us-central1"
export GOOGLE_GENAI_USE_VERTEXAI="1"
export GITHUB_TOKEN="ghp_..."
export MONGODB_CLIENT_ID="..."
export MONGODB_CLIENT_SECRET="..."
```

### 5. Start the MongoDB MCP server (separate terminal)

Open a new terminal window, export the same env vars, then run:

```bash
npx -y mongodb-mcp-server --transport http --port 3000
```

Leave this terminal running. The agent connects to it at `http://127.0.0.1:3000/mcp` using Streamable HTTP transport.

### 6. Start the agent

Back in your original terminal:

```bash
adk web
```

Open **http://localhost:8080** in your browser and start chatting.

---

## Usage Examples

### Indexing and search

```
Index https://github.com/openai/tiktoken so I can search it.

Search the tiktoken repo for "byte pair encoding" and show me the most relevant files.

Explain the file tiktoken/core.py in detail.
```

### Code analysis

```
Find security issues in tiktoken/core.py.

Generate Markdown documentation for tiktoken/model.py.

Audit the dependencies in https://github.com/openai/tiktoken.
```

### Git and commits

```
Summarise the last 10 commits on https://github.com/openai/tiktoken.

Create a GitHub issue on https://github.com/my-org/my-repo titled
"Fix memory leak in worker pool" describing the problem and suggested fix.
```

### Pull request workflow

```
List all open pull requests on https://github.com/my-org/my-repo.

Review PR #42 on https://github.com/my-org/my-repo and tell me if it's safe to merge.
```

The agent will:
1. Fetch the diff, files changed, and description
2. Run static analysis on the diff for security patterns
3. Present a full report with a recommended action (APPROVE / REQUEST_CHANGES / COMMENT)
4. **Ask for your confirmation** before submitting anything to GitHub

```
Submit the review as REQUEST_CHANGES with the comment you drafted.

Merge PR #42 using squash merge.

Log the review decision to MongoDB.
```

---

## Docker

The Dockerfile starts the MongoDB MCP server as a background process inside the container before launching the ADK web server.

```bash
# Build the image
docker build -t mongodb-codebase-agent .

# Run (pass all env vars at runtime)
docker run -p 8080:8080 \
  -e MONGODB_URI="mongodb+srv://..." \
  -e GOOGLE_CLOUD_PROJECT="your-project" \
  -e GOOGLE_CLOUD_LOCATION="us-central1" \
  -e GOOGLE_GENAI_USE_VERTEXAI="1" \
  -e GITHUB_TOKEN="ghp_..." \
  -e MONGODB_CLIENT_ID="..." \
  -e MONGODB_CLIENT_SECRET="..." \
  mongodb-codebase-agent
```

---

## Project Structure

```
mongodb-codebase-agent/
├── mongodb_agent/
│   ├── __init__.py      # Package init — imports agent module
│   ├── agent.py         # ADK Agent definition, MCP toolset, system prompt
│   └── tools.py         # All 16 Python tools (GitHub API + MongoDB)
├── startup.sh           # Container entrypoint — starts MCP server then adk web
├── requirements.txt     # Python dependencies
├── Dockerfile
├── .dockerignore
├── .gitignore
└── README.md
```

---

## Troubleshooting

**`KeyError: 'MONGODB_URI'`**
The environment variable is not exported in the current shell. Run the export commands in step 4 and try again.

**`Failed to create MCP session`**
The MongoDB MCP server is not running. Open a separate terminal and run:
```bash
npx -y mongodb-mcp-server --transport http --port 3000
```

**`No results found` from `search_codebase`**
Either the repo has not been indexed yet (run `index_repository` first), or the `vector_index` has not been created in Atlas (see [MongoDB Atlas Setup](#mongodb-atlas-setup)).

**`Vector Search not available` / index creation fails**
You are on the free M0 tier. Upgrade to **Atlas Flex** or a dedicated cluster (M10+) to enable Vector Search.

**Slow first index**
Large repos take a few minutes. Files over 500 KB are skipped automatically and file content is truncated to 25 000 characters before embedding to stay within API token limits.

**`Invalid option: expected one of 'stdio'|'http'`**
Your installed version of `mongodb-mcp-server` does not support SSE transport. Use `--transport http` (already set in `startup.sh`).
