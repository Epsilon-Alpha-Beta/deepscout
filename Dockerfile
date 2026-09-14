FROM public.ecr.aws/docker/library/python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

ARG PIP_INDEX_URL=https://pypi.org/simple

WORKDIR /app

RUN useradd --create-home --uid 10001 deepscout

COPY deploy/requirements.lock.txt /tmp/requirements.lock.txt
RUN pip install --no-cache-dir --require-hashes \
    --index-url "$PIP_INDEX_URL" \
    --timeout 120 --retries 5 \
    -r /tmp/requirements.lock.txt

COPY pyproject.toml README.md ./
COPY src ./src
COPY scripts ./scripts

RUN chown -R deepscout:deepscout /app

USER deepscout
ENV PYTHONPATH="/app/src" \
    DEEPSCOUT_API_HOST=0.0.0.0 \
    DEEPSCOUT_API_PORT=8000
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=2)"

CMD ["python", "scripts/run_api.py"]
