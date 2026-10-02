# Codebase Intelligence Agent

**An agentic RAG system that indexes any GitHub repository into MongoDB Atlas Vector Search, then reviews pull requests, finds bugs, audits dependencies, and answers plain-English questions about the code.**

Built with Google ADK and Gemini 2.5 Flash on Vertex AI, with 16 custom tools plus the MongoDB MCP server. Human-in-the-loop by design: the agent never submits a review or merges a PR without explicit confirmation.

> **No hosted demo.** The agent runs on my own API credentials, so there's no public instance. You can run it locally with your own keys (see [Run it yourself](#run-it-yourself)).

---

## How it works

1. **Index.** Fetches every code file from a GitHub repo, embeds each with `text-embedding-004` (768 dimensions), and stores content, embeddings, and metadata in MongoDB Atlas.
2. **Retrieve.** Atlas Vector Search (cosine similarity) finds the most relevant files for any question, scoped to a single repo with a filter field.
3. **Reason and act.** Gemini 2.5 Flash runs an agentic tool loop over the retrieved context and can take real actions on GitHub: filing issues, commenting on PRs, opening and merging pull requests.
4. **Audit.** Every PR review decision and its reasoning is logged to a `pr_reviews` collection in MongoDB.

## Architecture

```
┌─────────────────────────────────────────┐
│              ADK Web UI                 │
└────────────────┬────────────────────────┘
                 │
     ┌───────────▼───────────┐
     │   Gemini 2.5 Flash    │  (Vertex AI)
     └───────────┬───────────┘
                 │ tool calls
      ┌──────────┴──────────────────┐
      │                             │
┌─────▼──────┐          ┌───────────▼─────────┐
│ 16 Python  │          │ MongoDB MCP Server  │
│ tools      │          │ (Streamable HTTP)   │
└─────┬──────┘          └───────────┬─────────┘
      │                             │
┌─────▼─────────────────────────────▼─┐
│          MongoDB Atlas              │
│  codebase    (vector search)        │
│  pr_reviews  (audit log)            │
└─────────────────────────────────────┘
      │
┌─────▼──────────────┐
│   GitHub REST API  │
└────────────────────┘
```

## Tools

| Category | Tools |
|---|---|
| **RAG and search** | `index_repository`, `search_codebase`, `explain_code` |
| **Code analysis** | `find_bugs` (static analysis + LLM review), `generate_documentation`, `audit_dependencies` |
| **Pull requests** | `list_pull_requests`, `review_pull_request`, `submit_pr_review`, `merge_pull_request`, `add_code_comment`, `create_pull_request` |
| **Repo actions** | `create_github_issue`, `summarize_recent_commits` |
| **Data** | `log_pr_review`, `update_mongodb_document`, plus full Atlas access via the MongoDB MCP server |

### Human-in-the-loop PR review

`review_pull_request` fetches the diff, runs static analysis for security patterns, and returns a recommended APPROVE / REQUEST_CHANGES / COMMENT with reasoning, but never submits on its own. The agent always asks for confirmation before calling `submit_pr_review` or `merge_pull_request`.

## Tech stack

| Component | Technology |
|---|---|
| Agent framework | Google ADK 2.0 |
| LLM | Gemini 2.5 Flash (Vertex AI) |
| Embeddings | `text-embedding-004`, 768 dimensions |
| Vector database | MongoDB Atlas Vector Search |
| MCP integration | `mongodb-mcp-server` (Streamable HTTP transport) |
| Integrations | GitHub REST API, pymongo |
| Deployment | Docker, Google Cloud Run |

## Example prompts

```
Index https://github.com/openai/tiktoken so I can search it.
Search the tiktoken repo for "byte pair encoding" and show the most relevant files.
Find security issues in tiktoken/core.py.
Review PR #42 on https://github.com/my-org/my-repo and tell me if it's safe to merge.
```

---

## Run it yourself

<details>
<summary><b>Prerequisites</b></summary>

- Python 3.11+ and Node.js 18+
- MongoDB Atlas cluster on **Flex tier or higher** (Vector Search isn't available on free M0)
- Google Cloud project with Vertex AI enabled and application default credentials
- GitHub personal access token (`repo` scope)
- MongoDB Atlas API key pair (for the MCP server)
</details>

<details>
<summary><b>1. Create the Atlas vector index</b></summary>

In Atlas: your cluster → Search → Create Search Index → JSON Editor. Select `codebase_db.codebase`, name the index `vector_index`, and paste:

```json
{
  "fields": [
    { "type": "vector", "path": "embedding", "numDimensions": 768, "similarity": "cosine" },
    { "type": "filter", "path": "repo_url" }
  ]
}
```
</details>

<details>
<summary><b>2. Install and configure</b></summary>

```bash
git clone https://github.com/simonlunay/MongoDB-codebase-agent.git
cd MongoDB-codebase-agent
python -m venv venv && source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

Set these environment variables (a `.env` in the project root works, but they must be exported in each terminal you use):

```env
MONGODB_URI=mongodb+srv://<user>:<password>@<cluster>.mongodb.net/
GOOGLE_CLOUD_PROJECT=your-gcp-project-id
GOOGLE_CLOUD_LOCATION=us-central1
GOOGLE_GENAI_USE_VERTEXAI=1
GITHUB_TOKEN=ghp_...
MONGODB_CLIENT_ID=your-atlas-api-public-key
MONGODB_CLIENT_SECRET=your-atlas-api-private-key
```
</details>

<details>
<summary><b>3. Run</b></summary>

In one terminal, start the MongoDB MCP server:

```bash
npx -y mongodb-mcp-server --transport http --port 3000
```

In another, start the agent:

```bash
adk web
```

Open http://localhost:8080.

**Docker:** the container starts the MCP server in the background before launching the agent.

```bash
docker build -t mongodb-codebase-agent .
docker run -p 8080:8080 --env-file .env mongodb-codebase-agent
```
</details>

<details>
<summary><b>Troubleshooting</b></summary>

- **`KeyError: 'MONGODB_URI'`**: environment variables aren't exported in the current shell.
- **`Failed to create MCP session`**: the MongoDB MCP server isn't running.
- **No results from `search_codebase`**: index the repo first, and confirm `vector_index` exists in Atlas.
- **Vector Search unavailable**: you're on M0. Upgrade to Flex or M10+.
- **Slow first index**: large repos take a few minutes. Files over 500 KB are skipped and content is truncated to 25,000 characters before embedding.
</details>

## Project structure

```
MongoDB-codebase-agent/
├── mongodb_agent/
│   ├── agent.py      # Agent definition, MCP toolset, system prompt
│   └── tools.py      # 16 tools (GitHub API + MongoDB)
├── startup.sh        # Container entrypoint: MCP server, then adk web
├── Dockerfile
└── requirements.txt
```

---

Built by [Simon Lunay](https://www.simonlunay.com) · [LinkedIn](https://www.linkedin.com/in/simonlunay) · MIT License
