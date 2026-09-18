# API container for App Runner / ECS. Build from the backend/ directory.
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
ENV AGENTREHEARSAL_RUNS_DIR=/tmp/runs
EXPOSE 8000
CMD ["uvicorn", "agentrehearsal.api:app", "--host", "0.0.0.0", "--port", "8000"]
