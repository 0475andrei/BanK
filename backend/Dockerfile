FROM python:3.12-slim

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# tesseract-ocr-ron: Romanian language pack, for app/modules/id_ocr - ID
# cards are printed in Romanian. OCR runs fully offline/in-container, so
# no ID photo ever leaves this machine.
#
# cmake/build-essential: face_recognition's dlib dependency (app/modules/
# face_auth) has no prebuilt wheel for every platform, so pip may need to
# compile it from source here - same "runs fully offline, nothing ever
# leaves this machine" principle as the OCR above, just a heavier build.
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr tesseract-ocr-ron \
    cmake build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
COPY app ./app

RUN pip install --no-cache-dir ".[dev]" && rm -rf build *.egg-info

COPY tests ./tests
COPY scripts ./scripts
COPY docker-entrypoint.sh ./
# Strip CR first: checked out on Windows this file can arrive with CRLF, and
# a stray \r in the shebang makes the container die at startup with a very
# unhelpful "env: 'bash\r': No such file or directory". .gitattributes should
# prevent it, but this way the image builds correctly either way.
RUN sed -i 's/\r$//' docker-entrypoint.sh && chmod +x docker-entrypoint.sh

EXPOSE 8000

CMD ["./docker-entrypoint.sh"]
