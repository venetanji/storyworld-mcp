FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY src ./src
COPY characters ./characters
COPY images ./images
ENV PYTHONPATH=/app/src
# FastMCP (MCP protocol) - dev port
EXPOSE 3334
CMD ["python", "-m", "mcp_server.mcp_app"]
