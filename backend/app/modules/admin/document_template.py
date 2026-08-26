"""Renders an admin-authored document into PDF bytes, styled to look like an
actual bank document: logo, brand color header band, a bordered "titular"
info box, justified body text and a signature/footer block.

Pure function, no DB/network access - easy to unit test, and keeps
`admin/service.py` focused on orchestration (load user, create conversation,
store the document) rather than layout.

FONT: the base14 "helv" (Helvetica) shortcut pymupdf falls back to only
supports WinAnsiEncoding, which does NOT include ă/ș/ț (Romanian's
comma-below letters aren't in cp1252 at all - only â/î are, by accident of
overlapping with Western European accents). Rendered with "helv", "conținut"
comes out as "conţinut" - actually "con?inut" (a literal question mark).
DejaVu Sans covers the full Unicode range instead, so it is bundled here as
a real asset (assets/DejaVuSans*.ttf, copied from the vision container's
fonts - see that image's Dockerfile) and embedded via `fontfile=`, not
pulled from a system font path that may not exist in this image.

Single A4 page, deliberately not paginated: pymupdf's `insert_textbox`
reports overflow as a negative "missing space" number but does not report
which characters fit, so splitting text correctly across pages would need
its own line-wrapping logic. Given a page comfortably holds ~2000 characters
of body text at the font size used here, `AdminDocumentSendRequest.body` in
admin/schemas.py caps there instead - the admin gets a clear 422 telling
them to shorten the text rather than a document that silently loses its
ending.
"""

from __future__ import annotations

import uuid
from datetime import date
from pathlib import Path

import pymupdf

from app.core.exceptions import ValidationError

_ASSETS_DIR = Path(__file__).resolve().parent / "assets"
_LOGO_PATH = _ASSETS_DIR / "bank_logo.png"
_FONT_REGULAR_PATH = _ASSETS_DIR / "DejaVuSans.ttf"
_FONT_BOLD_PATH = _ASSETS_DIR / "DejaVuSans-Bold.ttf"

_MARGIN = 50
_PAGE_WIDTH, _PAGE_HEIGHT = pymupdf.paper_size("a4")
_CONTENT_RIGHT = _PAGE_WIDTH - _MARGIN

_FONT_REGULAR = "dejavu"
_FONT_BOLD = "dejavu-bold"

#: A real Font object, not just the page-registered name string above -
#: `pymupdf.get_text_length` (the module-level helper) only recognises the
#: base14 fonts, so measuring a custom embedded font's width needs this
#: instead (see _draw_holder_info_box's `field` helper).
_BOLD_FONT = pymupdf.Font(fontfile=str(_FONT_BOLD_PATH))

#: BanK's brand teal (frontend/style.css --primary-teal: #2DD4BF), and two
#: shades derived from it for use on a WHITE page - the bright original is
#: an accent-bar/border color here, not body text (too low-contrast on
#: white at text size).
_TEAL = (0.176, 0.831, 0.749)
_TEAL_DARK = (0.051, 0.580, 0.533)
_TEAL_TINT = (0.941, 0.992, 0.980)
_TEXT_DARK = (0.118, 0.161, 0.231)
_TEXT_MUTED = (0.392, 0.455, 0.545)

#: Cosmetic only - not stored or tracked anywhere else. Gives the document
#: the "this is a real numbered record" look an official one would have,
#: without pretending there is a registry behind it.
_REFERENCE_PREFIX = "BK"


def _new_reference() -> str:
    today = date.today()
    return f"{_REFERENCE_PREFIX}-{today.strftime('%Y%m')}-{uuid.uuid4().hex[:6].upper()}"


def _register_fonts(page: pymupdf.Page) -> None:
    page.insert_font(fontname=_FONT_REGULAR, fontfile=str(_FONT_REGULAR_PATH))
    page.insert_font(fontname=_FONT_BOLD, fontfile=str(_FONT_BOLD_PATH))


def _draw_header(page: pymupdf.Page, *, reference: str, issued_at: date) -> None:
    if _LOGO_PATH.exists():
        page.insert_image(pymupdf.Rect(_MARGIN, 40, _MARGIN + 40, 80), filename=str(_LOGO_PATH))

    page.insert_text((_MARGIN + 50, 58), "BanK", fontsize=18, fontname=_FONT_BOLD, color=_TEAL_DARK)
    page.insert_text(
        (_MARGIN + 50, 73), "CONFORTUL TĂU FINANCIAR", fontsize=7, fontname=_FONT_REGULAR,
        color=_TEXT_MUTED,
    )

    meta_rect = pymupdf.Rect(300, 42, _CONTENT_RIGHT, 80)
    meta_text = f"Nr. document: {reference}\nData: {issued_at.strftime('%d.%m.%Y')}"
    page.insert_textbox(
        meta_rect, meta_text, fontsize=9, fontname=_FONT_REGULAR, color=_TEXT_MUTED,
        align=pymupdf.TEXT_ALIGN_RIGHT,
    )

    # The header band itself - bleeds to both page edges, unlike everything
    # else which respects _MARGIN, so it reads as a banner, not a rule.
    page.draw_rect(pymupdf.Rect(0, 92, _PAGE_WIDTH, 96), color=None, fill=_TEAL)


#: Fixed layout constants for the title and info box below. Deliberately
#: NOT computed from actual content height: pymupdf draws text the instant
#: insert_text/insert_textbox is called (there is no measure-then-draw
#: pass), so a box that must be filled FIRST - to sit visually behind its
#: own text - can't size itself from that text's real height without a
#: second, throwaway render pass. Fixed, generous allowances are simpler
#: and can never overlap; the trade-off is a little unused whitespace when
#: a title/name/address is short, which is the common case anyway.
_TITLE_TOP = 108
_TITLE_HEIGHT = 46
_BOX_TOP = _TITLE_TOP + _TITLE_HEIGHT + 22
_BOX_HEIGHT = 155
_BODY_TOP = _BOX_TOP + _BOX_HEIGHT + 25


def _draw_title(page: pymupdf.Page, title: str) -> None:
    rect = pymupdf.Rect(_MARGIN, _TITLE_TOP, _CONTENT_RIGHT, _TITLE_TOP + _TITLE_HEIGHT)
    spare = page.insert_textbox(
        rect, title.upper(), fontsize=16, fontname=_FONT_BOLD, color=_TEXT_DARK,
    )
    if spare < 0:
        raise ValidationError("Titlul documentului este prea lung - scurtează-l.")

    line_y = _TITLE_TOP + _TITLE_HEIGHT - 8
    page.draw_line((_MARGIN, line_y), (_MARGIN + 60, line_y), color=_TEAL, width=2)


def _insert_wrapping_field(
    page: pymupdf.Page, rect: pymupdf.Rect, label: str, value: str
) -> None:
    """A "**Label:** value" row that WRAPS within `rect` instead of running
    past the page edge - the failure mode a plain single-line insert_text
    call has no defence against, and the one that actually broke on a long
    real address (see this module's docstring)."""
    page.insert_text(
        (rect.x0, rect.y0 + 10), label, fontsize=10, fontname=_FONT_BOLD, color=_TEXT_DARK
    )
    label_width = _BOLD_FONT.text_length(label, fontsize=10)

    value_rect = pymupdf.Rect(rect.x0 + label_width + 4, rect.y0, rect.x1, rect.y1)
    spare = page.insert_textbox(
        value_rect, value, fontsize=10, fontname=_FONT_REGULAR, color=_TEXT_DARK
    )
    if spare < 0:
        raise ValidationError(
            "Datele titularului sunt prea lungi pentru șablonul documentului."
        )


def _draw_holder_info_box(
    page: pymupdf.Page,
    *,
    first_name: str,
    last_name: str,
    national_id: str | None,
    address: str | None,
    issued_at: date,
) -> None:
    box = pymupdf.Rect(_MARGIN, _BOX_TOP, _CONTENT_RIGHT, _BOX_TOP + _BOX_HEIGHT)
    page.draw_rect(box, color=_TEAL_DARK, fill=_TEAL_TINT, width=0.75)

    inner_left = _MARGIN + 12
    inner_right = _CONTENT_RIGHT - 12
    page.insert_text(
        (inner_left, _BOX_TOP + 17), "DATE TITULAR",
        fontsize=8, fontname=_FONT_BOLD, color=_TEAL_DARK,
    )

    # Full-width, stacked rows - not a two-column "Nume / CNP" layout. A
    # fixed CNP column next to a wrapping name would still collide the
    # moment the name wraps to a second line; stacking removes that risk
    # entirely instead of bounding it.
    _insert_wrapping_field(
        page, pymupdf.Rect(inner_left, _BOX_TOP + 25, inner_right, _BOX_TOP + 25 + 28),
        "Nume:", f"{first_name} {last_name}",
    )
    _insert_wrapping_field(
        page, pymupdf.Rect(inner_left, _BOX_TOP + 55, inner_right, _BOX_TOP + 55 + 16),
        "CNP:", national_id or "-",
    )
    _insert_wrapping_field(
        page, pymupdf.Rect(inner_left, _BOX_TOP + 73, inner_right, _BOX_TOP + 73 + 44),
        "Adresă:", address or "-",
    )
    _insert_wrapping_field(
        page, pymupdf.Rect(inner_left, _BOX_TOP + 125, inner_right, _BOX_TOP + 125 + 16),
        "Data emiterii:", issued_at.strftime("%d.%m.%Y"),
    )


def _draw_signature_block(page: pymupdf.Page, *, first_name: str, last_name: str) -> None:
    y = _PAGE_HEIGHT - 130
    page.draw_line((_MARGIN, y), (_MARGIN + 200, y), color=_TEXT_MUTED, width=0.75)
    page.insert_text(
        (_MARGIN, y + 14), f"Semnătură titular ({first_name} {last_name})",
        fontsize=9, fontname=_FONT_REGULAR, color=_TEXT_MUTED,
    )


def _draw_footer(page: pymupdf.Page, reference: str) -> None:
    y = _PAGE_HEIGHT - 60
    page.draw_line((_MARGIN, y), (_CONTENT_RIGHT, y), color=_TEAL, width=1)
    page.insert_textbox(
        pymupdf.Rect(_MARGIN, y + 8, _CONTENT_RIGHT, y + 40),
        f"BanK S.A. · Document generat electronic prin sistemul BanK · Referință {reference}\n"
        "Nu necesită semnătură olografă sau ștampilă pentru a fi valid electronic.",
        fontsize=7, fontname=_FONT_REGULAR, color=_TEXT_MUTED, align=pymupdf.TEXT_ALIGN_CENTER,
    )


def render_document_pdf(
    *,
    title: str,
    body: str,
    first_name: str,
    last_name: str,
    national_id: str | None,
    address: str | None,
) -> bytes:
    issued_at = date.today()
    reference = _new_reference()

    doc = pymupdf.open()
    page = doc.new_page(width=_PAGE_WIDTH, height=_PAGE_HEIGHT)
    _register_fonts(page)

    _draw_header(page, reference=reference, issued_at=issued_at)
    _draw_title(page, title)
    _draw_holder_info_box(
        page,
        first_name=first_name,
        last_name=last_name,
        national_id=national_id,
        address=address,
        issued_at=issued_at,
    )

    body_rect = pymupdf.Rect(_MARGIN, _BODY_TOP, _CONTENT_RIGHT, _PAGE_HEIGHT - 145)
    overflow = page.insert_textbox(
        body_rect, body, fontsize=11, fontname=_FONT_REGULAR, color=_TEXT_DARK,
        align=pymupdf.TEXT_ALIGN_JUSTIFY,
    )
    if overflow < 0:
        raise ValidationError(
            "Textul documentului este prea lung pentru o singură pagină - scurtează-l."
        )

    _draw_signature_block(page, first_name=first_name, last_name=last_name)
    _draw_footer(page, reference)

    # Without this, both embedded DejaVu Sans files (regular + bold, ~1.4MB
    # together) ride along in full on every single document, even though a
    # one-page adeverință only ever uses a few dozen distinct glyphs from
    # them. Subsetting keeps only the glyphs actually drawn above, which is
    # the difference between a ~1.8MB PDF and one a few tens of KB.
    doc.subset_fonts()

    pdf_bytes = doc.tobytes()
    doc.close()
    return pdf_bytes
