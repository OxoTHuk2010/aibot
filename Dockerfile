FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN groupadd --system app && useradd --system --gid app --home-dir /app app

COPY pyproject.toml README.md LICENSE ./
COPY app ./app

RUN python -m pip install --upgrade "pip>=25,<26" && \
    python -m pip install .

USER app

CMD ["python", "-m", "app.main"]
