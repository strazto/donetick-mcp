FROM python:3.13-slim@sha256:d98cc29d3266e535dd9da1099688d9cb3ca4753813571e071763d17725460962 AS python

FROM python AS build
COPY --from=ghcr.io/astral-sh/uv:0.13.9@sha256:d3b601f0c7b118bc1753febf7c41cc80981df678445e0254284eecf84db79a7d /uv /usr/local/bin/uv
ENV UV_PYTHON_DOWNLOADS=never
WORKDIR /opt/donetick-mcp
COPY pyproject.toml uv.lock README.md LICENSE ./
RUN uv sync --locked --no-dev --no-install-project
COPY src/ src/
RUN uv sync --locked --no-dev --no-editable

FROM python AS runtime
COPY --from=build /opt/donetick-mcp/.venv /opt/donetick-mcp/.venv
ENV PATH="/opt/donetick-mcp/.venv/bin:${PATH}" PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 HOME=/tmp
USER 65532:65532
ENTRYPOINT ["donetick-mcp"]

FROM runtime AS tunnel
COPY --from=ghcr.io/openai/tunnel-client:v0.0.18@sha256:486321616c197fed2d3fbe7d44f22433ce9a1e6c1ee434c0d6652868a5fda5c1 /usr/bin/tunnel-client /usr/local/bin/tunnel-client
ENTRYPOINT ["tunnel-client", "run", "--mcp.command", "donetick-mcp"]

FROM runtime AS stdio
