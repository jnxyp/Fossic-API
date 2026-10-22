FROM python:3.11.17-slim-bookworm@sha256:f06d01d4ba3f8ad5af45a3ec87df19c1d317d8e8961edc0fabda61811af6f7cf AS base

ENV PYTHONUTF8=1 PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
RUN groupadd --gid 10001 app && useradd --uid 10001 --gid app --no-create-home app
COPY requirements.lock .
RUN python -m pip install --no-cache-dir --upgrade pip==26.2.2 setuptools==84.2.1 wheel==0.48.0 \
    && python -m pip install --no-cache-dir --require-hashes -r requirements.lock \
    && python -m pip check
# Production source is bind-mounted; also include it for isolated image testing.
COPY --chown=app:app src/ ./
USER app
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--log-config", "log_config.json"]

# Offline regression image; no .env or external DB is copied into either stage.
FROM base AS test
USER root
COPY requirements-dev.lock ./
RUN python -m pip install --no-cache-dir --require-hashes -r requirements-dev.lock \
    && python -m pip check
COPY --chown=app:app tests/ ./tests/
COPY --chown=app:app pytest.ini ./
USER app
ENV PYTHON_DOTENV_DISABLED=1
CMD ["python", "-m", "pytest", "-q", "-p", "no:cacheprovider"]

FROM base AS runtime
