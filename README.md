# MongoDB Codebase Agent

An autonomous AI agent that indexes GitHub repositories into **MongoDB Atlas Vector Search**, then lets you search, analyse, and act on any codebase using natural language — powered by **Google ADK 2.0** and **Gemini 2.5 Flash**.

---

## Features

| Capability | Tool |
|---|---|
| Index a GitHub repo (embeddings → Atlas) | `index_repository` |
| Semantic code search | `search_codebase` |
| Explain any file | `explain_code` |
| Find bugs & security issues | `find_bugs` |
| Generate Markdown documentation | `generate_documentation` |
| Audit dependencies for vulnerabilities | `audit_dependencies` |
| Summarise recent commits | `summarize_recent_commits` |
| Create GitHub issues | `create_github_issue` |
| Create GitHub pull requests | `create_pull_request` |
| Post PR review comments | `add_code_comment` |
| Update MongoDB documents directly | `update_mongodb_document` |
| Full MongoDB Atlas access via MCP | MongoDB MCP Server (Streamable HTTP) |

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
│ tools.py   │          │ (Streamable HTTP)    │
│ (11 tools) │          │ localhost:3000/mcp   │
└─────┬──────┘          └──────────┬──────────┘
      │                            │
      │          ┌─────────────────┘
      │          │
┌─────▼──────────▼────────────────┐
│       MongoDB Atlas              │
│  • codebase collection           │
│  • vector_index (768-dim)        │
│  • text-embedding-004 vectors    │
└──────────────────────────────────┘
      │
┌─────▼──────────────┐
│   GitHub API       │
│  (issues / PRs /   │
│   commits / files) │
└────────────────────┘
```

---

## Prerequisites

- Python 3.11+
- Node.js 18+ and `npx` (for the MongoDB MCP server)
- A [MongoDB Atlas](https://www.mongodb.com/atlas) cluster with Vector Search enabled
- A [Google Cloud](https://console.cloud.google.com) project with Vertex AI API enabled
- A GitHub [Personal Access Token](https://github.com/settings/tokens) (scopes: `repo`)
- A MongoDB Atlas [API key](https://www.mongodb.com/docs/atlas/configure-api-access/) (for the MCP server)

---

## Environment Variables

Create a `.env` file (never committed — see `.gitignore`) or export these in your shell:

```env
# MongoDB
MONGODB_URI=mongodb+srv://<user>:<pass>@<cluster>.mongodb.net/?appName=<app>

# Google Cloud / Vertex AI
GOOGLE_CLOUD_PROJECT=your-gcp-project-id
GOOGLE_CLOUD_LOCATION=us-central1
GOOGLE_GENAI_USE_VERTEXAI=1

# GitHub
GITHUB_TOKEN=ghp_...

# MongoDB Atlas API (for MCP server)
MONGODB_CLIENT_ID=your-atlas-api-client-id
MONGODB_CLIENT_SECRET=your-atlas-api-client-secret
```

> **Note:** The agent reads all variables directly from `os.environ`. Never call `load_dotenv` — set them in your shell, `.env` (loaded by your runner), or as container environment variables.

---

## MongoDB Atlas Setup

### 1. Create the Vector Search index

In the Atlas UI go to **Search → Create Search Index → JSON Editor**, select the `codebase_db.codebase` collection, and paste:

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

Name the index **`vector_index`**. `text-embedding-004` produces 768-dimensional vectors.

### 2. Collection schema (auto-created on first index)

| Field | Type | Description |
|---|---|---|
| `repo_url` | string | Canonical GitHub URL |
| `file_path` | string | Path within the repo |
| `content` | string | Full file source |
| `embedding` | array[float] | 768-dim vector |
| `language` | string | Detected language |

---

## Local Development

```bash
# 1. Clone and create a virtual environment
git clone https://github.com/your-org/mongodb-codebase-agent.git
cd mongodb-codebase-agent
python -m venv venv
venv\Scripts\activate        # Windows
# source venv/bin/activate   # macOS / Linux

# 2. Install dependencies
pip install -r requirements.txt

# 3. Set environment variables (or load your .env)
set MONGODB_URI=...
set GOOGLE_CLOUD_PROJECT=...
set GOOGLE_CLOUD_LOCATION=us-central1
set GOOGLE_GENAI_USE_VERTEXAI=1
set GITHUB_TOKEN=...
set MONGODB_CLIENT_ID=...
set MONGODB_CLIENT_SECRET=...

# 4. Start the MongoDB MCP server (separate terminal)
npx -y mongodb-mcp-server --transport http --port 3000

# 5. Start the ADK web UI
adk web
```

Then open **http://localhost:8080** and start chatting.

---

## Docker

```bash
# Build
docker build -t mongodb-codebase-agent .

# Start the MongoDB MCP server on the host first
npx -y mongodb-mcp-server --transport http --port 3000

# Run the container (use host networking so it can reach localhost:3000)
docker run --network host \
  -e MONGODB_URI="..." \
  -e GOOGLE_CLOUD_PROJECT="..." \
  -e GOOGLE_CLOUD_LOCATION="us-central1" \
  -e GOOGLE_GENAI_USE_VERTEXAI="1" \
  -e GITHUB_TOKEN="..." \
  -e MONGODB_CLIENT_ID="..." \
  -e MONGODB_CLIENT_SECRET="..." \
  mongodb-codebase-agent
```

---

## Example Prompts

```
Index https://github.com/openai/tiktoken and tell me how the BPE tokeniser works.

Search the tiktoken repo for "regex pattern" and show me the most relevant files.

Find security issues in tiktoken/core.py.

Generate documentation for tiktoken/model.py.

Audit the dependencies in the tiktoken repo.

Summarise the last 10 commits on https://github.com/openai/tiktoken.

Create a GitHub issue on https://github.com/my-org/my-repo titled "Fix memory leak in worker pool"
with a detailed description.
```

---

## Project Structure

```
mongodb-codebase-agent/
├── mongodb_agent/
│   ├── __init__.py      # from . import agent
│   ├── agent.py         # ADK Agent + MCP toolset definition
│   └── tools.py         # 11 Python tools (GitHub API + MongoDB)
├── requirements.txt
├── Dockerfile
├── .dockerignore
├── .gitignore
└── README.md
```

---

## Tech Stack

| Component | Technology |
|---|---|
| Agent framework | [Google ADK 2.0](https://google.github.io/adk-docs/) |
| LLM | Gemini 2.5 Flash (Vertex AI) |
| Embeddings | `text-embedding-004` (768-dim, Vertex AI) |
| Vector database | MongoDB Atlas Vector Search |
| MongoDB client | pymongo |
| MCP integration | `mongodb-mcp-server` via Streamable HTTP |
| GitHub integration | GitHub REST API v3 |

---

## Troubleshooting

**`KeyError: 'MONGODB_URI'`** — the environment variable is not set. Export it in your shell before running.

**`Failed to create MCP session`** — the MongoDB MCP server is not running. Start it first:
```bash
npx -y mongodb-mcp-server --transport http --port 3000
```

**`No results found` from `search_codebase`** — either the repo hasn't been indexed yet (`index_repository`) or the Atlas `vector_index` hasn't been created (see [Atlas Setup](#mongodb-atlas-setup)).

**`400 Bad Request` on MCP** — the agent is using SSE transport against a Streamable HTTP server. The correct params class is `StreamableHTTPConnectionParams` (already configured).

**Slow first index** — large repos can take a few minutes. Files over 500 KB are skipped automatically; text is truncated to 25 000 characters before embedding.
