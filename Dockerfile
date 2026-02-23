# Optional container for the Automaton Auditor
FROM python:3.11-slim

WORKDIR /app

# Install git for clone
RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY src/ src/
COPY rubric/ rubric/

ENV PYTHONPATH=/app
ENTRYPOINT ["python", "-m", "src.run_audit"]
