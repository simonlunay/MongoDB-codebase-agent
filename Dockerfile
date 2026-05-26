FROM python:3.11-slim

WORKDIR /app

# Install Node.js/npm so npx can run the MongoDB MCP server
RUN apt-get update && apt-get install -y nodejs npm && rm -rf /var/lib/apt/lists/*

# Install dependencies first (layer-cached unless requirements change)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy agent package
COPY mongodb_agent/ ./mongodb_agent/

EXPOSE 8080

CMD ["adk", "web", "--host", "0.0.0.0", "--port", "8080"]
