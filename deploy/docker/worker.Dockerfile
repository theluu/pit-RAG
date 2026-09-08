FROM python:3.12-slim
WORKDIR /app
# tesseract-ocr-vie carries the Vietnamese traineddata. PaddleOCR is deliberately not used:
# it classifies `vi` as Latin and its Latin dictionary has no tone-marked vowels, so it
# silently strips every dấu from the output.
RUN apt-get update && apt-get install -y --no-install-recommends \
      tesseract-ocr tesseract-ocr-vie libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*
COPY pyproject.toml README.md ./
COPY apps apps
COPY packages packages
RUN pip install --no-cache-dir '.[ocr]'
# Fail the build, not the first job, if the language data is missing.
RUN python -c "from packages.ingestion.pdf_pipeline import _ocr_engine; _ocr_engine()"
CMD ["dramatiq", "apps.worker.tasks", "--processes", "1", "--threads", "2"]
