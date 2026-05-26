#!/bin/sh

export MDB_MCP_CONNECTION_STRING="${MONGODB_URI}"

echo "=== Checking mongodb-mcp-server binary ==="
mongodb-mcp-server --version || echo "MCP binary not found"

echo "=== Locating binary in PATH ==="
which mongodb-mcp-server || echo "not in PATH"

echo "=== Starting MongoDB MCP server (transport: sse) ==="
mongodb-mcp-server --transport sse --logPath /tmp/mcp.log 2>&1 &

echo "=== Waiting 5 seconds for MCP server to initialise ==="
sleep 5

echo "=== MCP server log ==="
cat /tmp/mcp.log

echo "=== Starting ADK web server (port: 8080) ==="
adk web --host 0.0.0.0 --port 8080
