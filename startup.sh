#!/bin/sh
set -e

# Derive MDB_MCP_CONNECTION_STRING from MONGODB_URI so the MCP server
# process (which is separate from the Python agent process) gets the
# correct Atlas connection string at startup.
export MDB_MCP_CONNECTION_STRING="${MONGODB_URI}"

echo "Starting MongoDB MCP server (transport: http, port: 3000)..."
mongodb-mcp-server --transport http --port 3000 &

echo "Starting ADK web server (port: 8080)..."
exec adk web --host 0.0.0.0 --port 8080
