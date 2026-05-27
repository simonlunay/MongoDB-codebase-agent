import os

os.environ['GOOGLE_GENAI_USE_VERTEXAI'] = '1'

from google.adk.agents import Agent
from google.adk.tools.mcp_tool import McpToolset, StreamableHTTPConnectionParams

from mongodb_agent.tools import (
    index_repository,
    search_codebase,
    explain_code,
    find_bugs,
    create_github_issue,
    generate_documentation,
    update_mongodb_document,
    add_code_comment,
    create_pull_request,
    summarize_recent_commits,
    audit_dependencies,
    list_pull_requests,
    review_pull_request,
    submit_pr_review,
    merge_pull_request,
    log_pr_review,
)

# Expose MONGODB_URI as MDB_MCP_CONNECTION_STRING so any subprocess that
# spawns the MCP server (e.g. `npx -y mongodb-mcp-server --transport http`)
# inherits the correct connection string from this process's environment.
os.environ["MDB_MCP_CONNECTION_STRING"] = os.environ["MONGODB_URI"]

_mongodb_mcp = McpToolset(
    connection_params=StreamableHTTPConnectionParams(
        url="http://127.0.0.1:3000/mcp",
    )
)

root_agent = Agent(
    name="codebase_agent",
    model="gemini-2.5-flash",
    description="An autonomous agent that indexes, searches, analyzes, and takes action on GitHub codebases using MongoDB Atlas Vector Search",
    instruction=(
        "You are an expert software engineering assistant with access to a MongoDB Atlas "
        "vector database containing indexed GitHub repositories. You can:\n"
        "- Index GitHub repositories into MongoDB Atlas for semantic search\n"
        "- Search codebases using natural language queries\n"
        "- Explain code files in detail\n"
        "- Find bugs and security vulnerabilities\n"
        "- Generate markdown documentation\n"
        "- Create GitHub issues, pull requests, and PR review comments\n"
        "- List, review, submit reviews on, and merge pull requests\n"
        "- Log PR review decisions and reasoning to MongoDB\n"
        "- Update MongoDB documents directly\n"
        "- Summarize recent git commits\n"
        "- Audit project dependencies for security risks\n\n"
        "## PR Review — Human-in-the-Loop Rule\n\n"
        "IMPORTANT: When reviewing a pull request, you MUST follow this exact sequence:\n\n"
        "1. Call review_pull_request to fetch the diff and analysis.\n"
        "2. Present the full analysis, security flags, concerns, and the recommended "
        "action (APPROVE / REQUEST_CHANGES / COMMENT) to the user with your own reasoning.\n"
        "3. STOP and explicitly ask the user: 'Would you like me to submit this review "
        "to GitHub, or would you like to change the decision or comment?'\n"
        "4. Only call submit_pr_review after the user has given explicit confirmation.\n"
        "5. After submitting, offer to call log_pr_review to record the decision in MongoDB.\n\n"
        "NEVER call submit_pr_review or merge_pull_request without explicit user approval "
        "in that conversation turn. These are irreversible actions on the GitHub repository.\n\n"
        "Always be precise, thorough, and actionable in your responses. "
        "When analyzing code, provide concrete examples and line references when possible."
    ),
    tools=[
        index_repository,
        search_codebase,
        explain_code,
        find_bugs,
        create_github_issue,
        generate_documentation,
        update_mongodb_document,
        add_code_comment,
        create_pull_request,
        summarize_recent_commits,
        audit_dependencies,
        list_pull_requests,
        review_pull_request,
        submit_pr_review,
        merge_pull_request,
        log_pr_review,
        _mongodb_mcp,
    ],
)
