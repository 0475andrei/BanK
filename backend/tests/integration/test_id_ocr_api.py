import io

from PIL import Image, ImageDraw, ImageFont

from app.modules.auth.validation import generate_test_national_id

_FONT_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"


def _render_id_card_png(cnp: str) -> bytes:
    lines = [
        "CNP " + cnp,
        "Nume/Nom",
        "POPESCU",
        "Prenume/Prenom",
        "ANDREI ION",
        "Domiciliu/Adresse",
        "STR EXEMPLU NR 1 BUCURESTI",
    ]
    font = ImageFont.truetype(_FONT_PATH, 28)
    image = Image.new("RGB", (900, 320), "white")
    draw = ImageDraw.Draw(image)
    for i, line in enumerate(lines):
        draw.text((20, 20 + i * 40), line, fill="black", font=font)

    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


async def test_extract_reads_cnp_name_and_address_from_photo(client):
    cnp = generate_test_national_id(1995, 6, 15, gender="F")
    png_bytes = _render_id_card_png(cnp)

    resp = await client.post(
        "/api/v1/id-ocr/extract",
        files={"file": ("id.png", png_bytes, "image/png")},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["national_id"] == cnp
    assert body["national_id_valid"] is True
    assert body["last_name"] == "POPESCU"
    assert body["first_name"] == "ANDREI ION"
    assert body["address"].startswith("STR EXEMPLU")
    assert body["date_of_birth"] == "1995-06-15"
    assert body["gender"] == "F"
    assert "raw_text" not in body


async def test_extract_requires_no_authentication(client):
    # This runs during registration, before any session exists.
    png_bytes = _render_id_card_png(generate_test_national_id(1990, 1, 1, gender="M"))
    resp = await client.post(
        "/api/v1/id-ocr/extract",
        files={"file": ("id.png", png_bytes, "image/png")},
    )
    assert resp.status_code == 200


async def test_extract_rejects_non_png_content_type(client):
    resp = await client.post(
        "/api/v1/id-ocr/extract",
        files={"file": ("id.jpg", b"not really a jpeg", "image/jpeg")},
    )
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "validation_error"


async def test_extract_rejects_unreadable_image(client):
    resp = await client.post(
        "/api/v1/id-ocr/extract",
        files={"file": ("id.png", b"this is not a valid png file", "image/png")},
    )
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "validation_error"


async def test_extract_rejects_empty_file(client):
    resp = await client.post(
        "/api/v1/id-ocr/extract",
        files={"file": ("id.png", b"", "image/png")},
    )
    assert resp.status_code == 422
