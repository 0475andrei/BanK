import io

import pymupdf
from PIL import Image, ImageDraw, ImageFilter, ImageFont

VALID_IBAN = "RO49AAAA1B31007593840000"
_FONT_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"


def _render_text_image(lines: list[str]) -> Image.Image:
    font = ImageFont.truetype(_FONT_PATH, 28)
    image = Image.new("RGB", (900, 320), "white")
    draw = ImageDraw.Draw(image)
    for i, line in enumerate(lines):
        draw.text((20, 20 + i * 40), line, fill="black", font=font)
    return image


def _to_png_bytes(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _render_pdf_bytes(pages: list[list[str]]) -> bytes:
    document = pymupdf.open()
    try:
        for lines in pages:
            page = document.new_page()
            for i, line in enumerate(lines):
                page.insert_text((50, 80 + i * 40), line, fontsize=18)
        return document.tobytes()
    finally:
        document.close()


async def test_extract_requires_authentication(client):
    png_bytes = _to_png_bytes(_render_text_image([VALID_IBAN]))
    resp = await client.post(
        "/api/v1/iban-ocr/extract", files={"file": ("card.png", png_bytes, "image/png")}
    )
    assert resp.status_code == 401


async def test_extract_reads_iban_from_photo(authed_client):
    client, _user = authed_client
    png_bytes = _to_png_bytes(_render_text_image(["Card holder: Ion Popescu", VALID_IBAN]))

    resp = await client.post(
        "/api/v1/iban-ocr/extract", files={"file": ("card.png", png_bytes, "image/png")}
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["iban"] == VALID_IBAN
    assert body["low_confidence"] is False
    assert body["ocr_confidence"] > 0


async def test_extract_reads_iban_with_spaced_grouping(authed_client):
    """IBANs are commonly printed in space-separated groups of 4. Double
    spaces between groups (not single) - tesseract reliably misreads
    "1B31" as "1B831" at single-space width with this font/size, an OCR
    rendering artifact unrelated to the extraction logic under test (which
    has its own direct, rendering-free coverage in tests/unit/test_iban_ocr.py)."""
    client, _user = authed_client
    spaced = "  ".join(VALID_IBAN[i : i + 4] for i in range(0, len(VALID_IBAN), 4))
    png_bytes = _to_png_bytes(_render_text_image([spaced]))

    resp = await client.post(
        "/api/v1/iban-ocr/extract", files={"file": ("card.png", png_bytes, "image/png")}
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["iban"] == VALID_IBAN


async def test_extract_ignores_checksum_invalid_lookalike(authed_client):
    """Proves the checksum, not just the pattern, gates a match - this
    string is IBAN-shaped but its check digits are wrong."""
    client, _user = authed_client
    fake = "RO00AAAA1B31007593840000"
    png_bytes = _to_png_bytes(_render_text_image([fake]))

    resp = await client.post(
        "/api/v1/iban-ocr/extract", files={"file": ("card.png", png_bytes, "image/png")}
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["iban"] is None
    assert body["low_confidence"] is True


async def test_extract_flags_low_confidence_when_no_iban_present(authed_client):
    client, _user = authed_client
    png_bytes = _to_png_bytes(_render_text_image(["Just a random receipt", "Total: 42.50 RON"]))

    resp = await client.post(
        "/api/v1/iban-ocr/extract", files={"file": ("card.png", png_bytes, "image/png")}
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["iban"] is None
    assert body["low_confidence"] is True


async def test_extract_flags_low_confidence_for_blurry_image(authed_client):
    client, _user = authed_client
    image = _render_text_image([VALID_IBAN])
    blurred = image.filter(ImageFilter.GaussianBlur(radius=8))
    png_bytes = _to_png_bytes(blurred)

    resp = await client.post(
        "/api/v1/iban-ocr/extract", files={"file": ("card.png", png_bytes, "image/png")}
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["low_confidence"] is True


async def test_extract_reads_iban_from_pdf(authed_client):
    client, _user = authed_client
    pdf_bytes = _render_pdf_bytes([["Extras de cont", VALID_IBAN]])

    resp = await client.post(
        "/api/v1/iban-ocr/extract",
        files={"file": ("statement.pdf", pdf_bytes, "application/pdf")},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["iban"] == VALID_IBAN
    assert body["low_confidence"] is False


async def test_extract_finds_iban_on_second_pdf_page(authed_client):
    """The IBAN isn't always on the first page of a statement - every page
    is tried in order (see extractor.py::extract_iban)."""
    client, _user = authed_client
    pdf_bytes = _render_pdf_bytes(
        [["Pagina 1 - fara IBAN aici"], ["Pagina 2", VALID_IBAN]]
    )

    resp = await client.post(
        "/api/v1/iban-ocr/extract",
        files={"file": ("statement.pdf", pdf_bytes, "application/pdf")},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["iban"] == VALID_IBAN


async def test_extract_prefers_pdf_text_layer_over_ocr(authed_client):
    """Regression test: a PDF with a real text layer (a generated
    statement/invoice, not a scan) must be read via that text layer, not
    rasterized and OCR'd - OCR can misread a character (e.g. "0" as "O")
    that the text layer never gets wrong. Uses the same unevenly-grouped
    spacing a real statement used when this bug was reported
    ("RO71 BANK4 JG9W 0MDT 6GE2SJE", not a neat groups-of-4 pattern)."""
    client, _user = authed_client
    iban = "RO71BANK4JG9W0MDT6GE2SJE"
    spaced = "RO71 BANK4 JG9W 0MDT 6GE2SJE"
    pdf_bytes = _render_pdf_bytes([["IBAN", spaced]])

    resp = await client.post(
        "/api/v1/iban-ocr/extract",
        files={"file": ("statement.pdf", pdf_bytes, "application/pdf")},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["iban"] == iban
    assert body["ocr_confidence"] == 100.0
    assert body["low_confidence"] is False


async def test_extract_rejects_unreadable_pdf(authed_client):
    client, _user = authed_client
    resp = await client.post(
        "/api/v1/iban-ocr/extract",
        files={"file": ("statement.pdf", b"not a real pdf", "application/pdf")},
    )
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "validation_error"


async def test_extract_rejects_non_image_content_type(authed_client):
    client, _user = authed_client
    resp = await client.post(
        "/api/v1/iban-ocr/extract",
        files={"file": ("card.jpg", b"not really a jpeg", "text/plain")},
    )
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "validation_error"


async def test_extract_rejects_unreadable_image(authed_client):
    client, _user = authed_client
    resp = await client.post(
        "/api/v1/iban-ocr/extract",
        files={"file": ("card.png", b"this is not a valid png file", "image/png")},
    )
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "validation_error"


async def test_extract_rejects_empty_file(authed_client):
    client, _user = authed_client
    resp = await client.post(
        "/api/v1/iban-ocr/extract", files={"file": ("card.png", b"", "image/png")}
    )
    assert resp.status_code == 422
