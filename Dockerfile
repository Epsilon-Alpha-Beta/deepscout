FROM public.ecr.aws/docker/library/python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app

RUN pip install --no-cache-dir uv \
    && useradd --create-home --uid 10001 deepscout

COPY pyproject.toml uv.lock README.md ./
COPY src ./src
COPY scripts ./scripts

RUN uv sync --frozen --no-dev --extra postgres \
    && chown -R deepscout:deepscout /app

USER deepscout
ENV PATH="/app/.venv/bin:${PATH}" \
    DEEPSCOUT_API_HOST=0.0.0.0 \
    DEEPSCOUT_API_PORT=8000
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=2)"

CMD ["python", "scripts/run_api.py"]
