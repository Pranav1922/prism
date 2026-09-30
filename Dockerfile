# Reproducible CPU-only environment for the tests, the black-box evaluator and the demos.
# Inside the container: the scripted planner (no model server), tesseract OCR for images, and the SCRIPTED
# transcripts for audio (the on-device ASR helper is macOS-only). See docs/SUBMISSION_READINESS.md.
FROM python:3.12-slim
RUN apt-get update \
 && apt-get install -y --no-install-recommends tesseract-ocr \
 && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY pyproject.toml README.md ./
COPY agent ./agent
COPY evaluation ./evaluation
COPY protocol ./protocol
COPY scripts ./scripts
COPY tests ./tests
COPY demo ./demo
COPY frontend ./frontend
RUN pip install --no-cache-dir -e ".[dev]"
ENV PYTHONHASHSEED=0
# default: full test suite, then the black-box evaluation of every scenario
CMD ["sh", "-c", "python -m pytest && python -m evaluation.run all --agent impl_a --out /tmp/report"]
