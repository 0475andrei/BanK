"""PDF text extraction for uploaded documents.

pymupdf only, for now - image uploads are a later step (see the module
docstring on router.py). Unlike iban_ocr/extractor.py, there is no OCR
fallback here: a scanned, no-text-layer PDF simply yields an empty string,
and DocumentAgent's system prompt is written to handle that case rather than
this module silently rasterizing and OCR'ing pages nobody asked it to.
"""

from __future__ import annotations

import pymupdf

from app.core.exceptions import ValidationError

MAX_FILE_SIZE_BYTES = 5 * 1024 * 1024  # 5 MB
ALLOWED_MIME_TYPES = {"application/pdf"}

#: The real PDF file signature (ISO 32000). Checked in addition to the
#: client-supplied Content-Type header, which is trivially spoofable - see
#: validate_pdf_magic_bytes below.
_PDF_MAGIC = b"%PDF-"


def validate_pdf_magic_bytes(content: bytes) -> None:
    """Verify the actual file signature, not just the Content-Type header.

    A client can label any file `application/pdf`; this is the defense in
    depth that catches it before the bytes ever reach pymupdf.
    """
    if not content.startswith(_PDF_MAGIC):
        raise ValidationError("Fișierul nu este un PDF valid.")


def extract_pdf_text(pdf_bytes: bytes) -> tuple[str, int]:
    """Extract text from PDF bytes. Returns (text, page_count).

    Raises ValidationError on a corrupt or unreadable PDF. An empty result
    (a scanned PDF with no text layer) is not an error - it still returns
    successfully with an empty string, and page_count from the document
    itself, since pymupdf can report page count even for a textless PDF.
    """
    try:
        document = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    except Exception as exc:
        raise ValidationError("PDF ilizibil sau corupt.") from exc

    try:
        page_count = document.page_count
        text = "\n".join(page.get_text() for page in document)
    except Exception as exc:
        raise ValidationError("PDF ilizibil sau corupt.") from exc
    finally:
        document.close()

    return text, page_count
