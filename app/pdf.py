"""PDF-Seiten rendern und Text lesen – mit pypdfium2 (Apache-2.0/BSD-3) und Pillow.

Ersetzt PyMuPDF (AGPL). Eine "Seite" ist hier ein Pillow-Bild (gerendert bzw. das
hochgeladene Foto) plus der Text der PDF-Textebene. Produktausschnitte werden direkt aus
dem gerenderten Seitenbild geschnitten.
"""
from __future__ import annotations

import base64
import io
from dataclasses import dataclass
from typing import Iterator

MAX_PX = 1600  # längste Kante des Seitenbilds (größer bringt der Vision-Eingabe nichts)


@dataclass
class Seite:
    bild: "object"          # PIL.Image.Image (RGB)
    text: str = ""


def _skala(breite: float, hoehe: float, max_px: int) -> float:
    # PDF-Einheiten sind Punkte (1/72 Zoll); Faktor 1 = 72 dpi. Wie bisher höchstens 2x.
    return min(max_px / max(breite, hoehe, 1.0), 2.0)


def pdf_seiten(quelle: "str | bytes", max_seiten: int, max_px: int = MAX_PX,
               mit_text: bool = True) -> Iterator[Seite]:
    """Liefert die ersten `max_seiten` Seiten eines PDFs (Pfad oder Bytes) als Seite-Objekte.
    Wirft bei unlesbarem PDF eine Exception (pypdfium2.PdfiumError o. ä.)."""
    import pypdfium2 as pdfium
    doc = pdfium.PdfDocument(quelle)
    try:
        for i in range(min(len(doc), max_seiten)):
            page = doc[i]
            try:
                b, h = page.get_size()
                bild = page.render(scale=_skala(b, h, max_px)).to_pil().convert("RGB")
                text = ""
                if mit_text:
                    tp = page.get_textpage()
                    try:
                        text = (tp.get_text_range() or "").strip()
                    finally:
                        tp.close()
                yield Seite(bild=bild, text=text)
            finally:
                page.close()
    finally:
        doc.close()


def seitenzahl(quelle: "str | bytes") -> int:
    import pypdfium2 as pdfium
    doc = pdfium.PdfDocument(quelle)
    try:
        return len(doc)
    finally:
        doc.close()


def bild_oeffnen(pfad: str, max_px: int = MAX_PX) -> Seite:
    """Einzelbild (JPEG/PNG/WebP …) als Seite laden, auf max_px verkleinert."""
    from PIL import Image, ImageOps
    with Image.open(pfad) as im:
        im = ImageOps.exif_transpose(im).convert("RGB")
        im.thumbnail((max_px, max_px), Image.LANCZOS)
        return Seite(bild=im.copy())


def data_url(bild, fmt: str = "PNG", qualitaet: int = 82) -> str:
    buf = io.BytesIO()
    if fmt.upper() == "JPEG":
        bild.save(buf, format="JPEG", quality=qualitaet, optimize=True)
        mt = "image/jpeg"
    else:
        bild.save(buf, format="PNG", optimize=True)
        mt = "image/png"
    return f"data:{mt};base64," + base64.b64encode(buf.getvalue()).decode()


def pdf_zu_data_urls(pdf_bytes: bytes, max_seiten: int, max_px: int = MAX_PX) -> list[str]:
    """PDF-Bytes -> PNG-Data-URLs der ersten Seiten ([] bei unlesbarem PDF)."""
    urls: list[str] = []
    try:
        for s in pdf_seiten(pdf_bytes, max_seiten, max_px, mit_text=False):
            urls.append(data_url(s.bild))
    except Exception:
        return urls
    return urls


def ausschnitt(bild, box, max_kante: int = 320, max_bytes: int = 60000) -> "str | None":
    """box=[ymin,xmin,ymax,xmax] normiert 0..1000 -> kleines JPEG-Data-URL des Ausschnitts.
    None bei ungültiger/zu kleiner Box oder zu großem Ergebnis."""
    from PIL import Image
    if bild is None or not isinstance(box, (list, tuple)) or len(box) != 4:
        return None
    try:
        ymin, xmin, ymax, xmax = (float(v) for v in box)
    except (TypeError, ValueError):
        return None
    w, h = bild.size
    x0 = max(0.0, min(xmin, xmax)) / 1000.0 * w
    x1 = min(1000.0, max(xmin, xmax)) / 1000.0 * w
    y0 = max(0.0, min(ymin, ymax)) / 1000.0 * h
    y1 = min(1000.0, max(ymin, ymax)) / 1000.0 * h
    if x1 - x0 < 8 or y1 - y0 < 8:
        return None
    teil = bild.crop((int(x0), int(y0), int(round(x1)), int(round(y1))))
    teil.thumbnail((max_kante, max_kante), Image.LANCZOS)
    url = data_url(teil, "JPEG", 68)
    if len(url) * 3 // 4 > max_bytes:
        return None
    return url
