FROM python:3.13-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir . && useradd --uid 10001 --no-create-home app
USER app
EXPOSE 8000
CMD ["uvicorn", "--factory", "payremind.api.app:create_app", "--host", "0.0.0.0", "--port", "8000"]
