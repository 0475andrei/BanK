"""Pre-auth endpoint: lets the registration form prefill itself from a photo
of the user's ID card. No session required - this runs before an account
exists. See extractor.py for what's actually extracted and why it's
local-only (no image ever leaves this machine)."""

import tempfile
from pathlib import Path

from fastapi import APIRouter, File, UploadFile

from app.core.exceptions import ValidationError
from app.modules.id_ocr.extractor import extract_id_fields
from app.modules.id_ocr.schemas import IdOcrResult

router = APIRouter()

# A phone photo of an ID card comfortably fits well under this; mainly a
# guard against someone pointing an unrelated multi-MB file at OCR.
_MAX_UPLOAD_BYTES = 8 * 1024 * 1024


@router.post("/extract", response_model=IdOcrResult)
async def extract(file: UploadFile = File(...)) -> IdOcrResult:
    if file.content_type != "image/png":
        raise ValidationError("Only PNG images are supported.")

    contents = await file.read()
    if not contents:
        raise ValidationError("Uploaded file is empty.")
    if len(contents) > _MAX_UPLOAD_BYTES:
        raise ValidationError("Image is too large (max 8 MB).")

    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
        tmp.write(contents)
        tmp_path = Path(tmp.name)

    try:
        fields = extract_id_fields(str(tmp_path))
    except Exception as exc:
        # PIL/tesseract can fail in many library-specific ways for a
        # corrupt or unreadable image - all of them mean the same thing to
        # the client: this isn't a readable ID photo, fill in manually.
        raise ValidationError("Could not read the ID photo. Try a clearer image.") from exc
    finally:
        tmp_path.unlink(missing_ok=True)

    return IdOcrResult(**{key: value for key, value in fields.items() if key != "raw_text"})
