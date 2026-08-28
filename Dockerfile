FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml .
COPY src ./src
COPY scripts ./scripts
RUN pip install --no-cache-dir -e .
ENV PYTHONPATH=/app/src:/app
EXPOSE 8080
