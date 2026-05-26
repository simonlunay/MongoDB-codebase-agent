FROM python:3.11-slim

WORKDIR /app

# Install Node.js and npm
RUN apt-get update && apt-get install -y nodejs npm && rm -rf /var/lib/apt/lists/*

# Install the MongoDB MCP server globally so it is on PATH without npx
RUN npm install -g mongodb-mcp-server

# Install Python dependencies (layer-cached unless requirements change)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy agent package and startup script
COPY mongodb_agent/ ./mongodb_agent/
COPY startup.sh .
RUN chmod +x startup.sh

EXPOSE 8080

# startup.sh starts mongodb-mcp-server in the background then execs adk web
CMD ["./startup.sh"]
