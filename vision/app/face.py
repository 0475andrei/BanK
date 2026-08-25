"""Face embedding extraction (dlib, via face_recognition).

This is the ONLY reason this service needs cmake and a C++ toolchain in its
image - and the reason it is a separate service at all. Everything the
banking backend does with faces afterwards (storing the embedding, comparing
two of them, issuing and consuming confirmation tokens) is plain arithmetic
and database work, and stays there.

Runs fully offline: the photo is processed in this container and is never
persisted anywhere - the caller gets back 128 floats and nothing else.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import face_recognition


class NoFaceDetectedError(Exception):
    """No face in the photo at all."""


class MultipleFacesDetectedError(Exception):
    """More than one face - ambiguous, so the caller must not guess."""


def extract_embedding(image_bytes: bytes) -> list[float]:
    """Return the 128-value face encoding for the single face in `image_bytes`.

    Goes through a temporary file because face_recognition.load_image_file
    wants a path; it is removed in the `finally` regardless of outcome, so a
    failed read never leaves a copy of someone's face on disk.
    """
    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
        tmp.write(image_bytes)
        tmp_path = Path(tmp.name)

    try:
        image = face_recognition.load_image_file(str(tmp_path))
        encodings = face_recognition.face_encodings(image)
    finally:
        tmp_path.unlink(missing_ok=True)

    if not encodings:
        raise NoFaceDetectedError()
    if len(encodings) > 1:
        raise MultipleFacesDetectedError()
    return encodings[0].tolist()
