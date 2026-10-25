"""Tests für app/pdf.py (pypdfium2 + Pillow) – erzeugt die Test-PDFs selbst."""
from __future__ import annotations

import base64
import io
import unittest

from PIL import Image

from app import pdf


def _text_pdf(text: str = "Angebot Tomaten 1,99") -> bytes:
    """Minimales einseitiges PDF (A4) mit einer Textzeile in Helvetica."""
    inhalt = f"BT /F1 24 Tf 72 720 Td ({text}) Tj ET".encode("latin-1")
    objekte = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
        b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        b"<< /Length " + str(len(inhalt)).encode() + b" >>\nstream\n" + inhalt + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = io.BytesIO()
    out.write(b"%PDF-1.4\n")
    offsets = []
    for i, obj in enumerate(objekte, 1):
        offsets.append(out.tell())
        out.write(f"{i} 0 obj\n".encode() + obj + b"\nendobj\n")
    xref = out.tell()
    out.write(f"xref\n0 {len(objekte) + 1}\n0000000000 65535 f \n".encode())
    for off in offsets:
        out.write(f"{off:010d} 00000 n \n".encode())
    out.write(f"trailer\n<< /Size {len(objekte) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode())
    return out.getvalue()


def _bild_pdf(seiten: int = 3) -> bytes:
    bilder = [Image.new("RGB", (600, 800), (40 * i, 100, 150)) for i in range(seiten)]
    buf = io.BytesIO()
    bilder[0].save(buf, format="PDF", save_all=True, append_images=bilder[1:])
    return buf.getvalue()


class PdfTests(unittest.TestCase):
    def test_text_und_render(self):
        seiten = list(pdf.pdf_seiten(_text_pdf(), max_seiten=5))
        self.assertEqual(len(seiten), 1)
        self.assertIn("Tomaten", seiten[0].text)
        b, h = seiten[0].bild.size
        self.assertEqual(max(b, h), 1600)            # auf 1600 px längste Kante skaliert

    def test_max_seiten_und_data_urls(self):
        daten = _bild_pdf(3)
        self.assertEqual(pdf.seitenzahl(daten), 3)
        urls = pdf.pdf_zu_data_urls(daten, max_seiten=2)
        self.assertEqual(len(urls), 2)
        self.assertTrue(urls[0].startswith("data:image/png;base64,"))
        roh = base64.b64decode(urls[0].split(",", 1)[1])
        self.assertEqual(Image.open(io.BytesIO(roh)).format, "PNG")

    def test_kaputtes_pdf(self):
        self.assertEqual(pdf.pdf_zu_data_urls(b"kein pdf", 3), [])
        with self.assertRaises(Exception):
            list(pdf.pdf_seiten(b"kein pdf", 3))

    def test_ausschnitt(self):
        bild = Image.new("RGB", (1000, 1000), (255, 0, 0))
        url = pdf.ausschnitt(bild, [100, 100, 600, 800])
        self.assertTrue(url.startswith("data:image/jpeg;base64,"))
        teil = Image.open(io.BytesIO(base64.b64decode(url.split(",", 1)[1])))
        self.assertLessEqual(max(teil.size), 320)
        self.assertIsNone(pdf.ausschnitt(bild, [0, 0, 1, 1]))       # zu klein
        self.assertIsNone(pdf.ausschnitt(bild, [1, 2, 3]))          # ungültig
        self.assertIsNone(pdf.ausschnitt(bild, ["a", 0, 10, 10]))


if __name__ == "__main__":
    unittest.main()
