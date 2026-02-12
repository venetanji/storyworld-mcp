# Stage 0: Builder - create a virtual environment and install Python deps
FROM python:3.12-alpine AS builder

ENV VIRTUAL_ENV=/opt/venv
ENV PATH="$VIRTUAL_ENV/bin:$PATH"

# Copy the `uv` binary from the official image for dependency management
COPY --from=ghcr.io/astral-sh/uv:alpine /uv /bin/uv
RUN chmod +x /bin/uv

# Create virtual environment using `uv` (falls back to ensure pip exists)
RUN uv venv $VIRTUAL_ENV || python -m venv $VIRTUAL_ENV

WORKDIR /app

# Copy lock/manifest files first to leverage Docker layer caching
COPY pyproject.toml uv.lock* requirements.txt ./

# Install dependencies: prefer `uv sync` when pyproject exists, otherwise pip
RUN if [ -f pyproject.toml ]; then \
			uv sync --locked || uv sync; \
		elif [ -f requirements.txt ]; then \
			pip install --no-cache-dir -r requirements.txt; \
		fi

# Stage 1: Runtime - copy virtualenv and application files
FROM python:3.12-alpine AS runtime

ENV VIRTUAL_ENV=/opt/venv
ENV PATH="$VIRTUAL_ENV/bin:$PATH"

# Bring the installed virtualenv from the builder
COPY --from=builder /opt/venv /opt/venv

WORKDIR /app

# Copy only the application files needed at runtime
COPY src ./src
COPY characters ./characters
COPY images ./images

ENV PYTHONPATH=/app/src

# FastMCP (MCP protocol) - dev port
EXPOSE 3334

CMD ["python", "-m", "mcp_server.mcp_app"]
