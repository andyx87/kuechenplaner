"""Erzeugt neutrale, textfreie Platzhalter-Icons (Topf-Symbol) für Web, PWA und Android.

TODO: echtes Artwork/Logo für Küchenplaner entwerfen und diese Platzhalter ersetzen.

Aufruf aus dem Repo-Wurzelverzeichnis (benötigt Pillow):
    python brand/build_placeholder.py
"""
import glob
import os

from PIL import Image, ImageDraw

BG = (47, 79, 79)        # Schiefergrün
FG = (245, 240, 230)     # Creme
BG_DARK = (22, 26, 30)
SS = 4                   # Supersampling


def pot(d, cx, cy, s, fg):
    """Zeichnet einen schlichten Kochtopf mit Deckel, zentriert bei (cx, cy), Breite ~s."""
    w = s
    h = s * 0.55
    x0, y0 = cx - w / 2, cy - h / 2 + s * 0.08
    # Topfkörper
    d.rounded_rectangle((x0, y0, x0 + w, y0 + h), radius=s * 0.12, fill=fg)
    # Griffe
    gh = s * 0.10
    d.rounded_rectangle((x0 - s * 0.14, y0 + s * 0.08, x0 + s * 0.02, y0 + s * 0.08 + gh), radius=gh / 2, fill=fg)
    d.rounded_rectangle((x0 + w - s * 0.02, y0 + s * 0.08, x0 + w + s * 0.14, y0 + s * 0.08 + gh), radius=gh / 2, fill=fg)
    # Deckel
    lt = y0 - s * 0.10
    d.rounded_rectangle((x0 - s * 0.04, lt, x0 + w + s * 0.04, y0 - s * 0.02), radius=s * 0.04, fill=fg)
    # Deckelknauf
    kr = s * 0.07
    d.ellipse((cx - kr, lt - kr * 1.6, cx + kr, lt + kr * 0.2), fill=fg)


def bild(w, h, bg=BG, frac=0.5, fg=FG, transparent=False):
    W, H = w * SS, h * SS
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0) if transparent else bg + (255,))
    pot(ImageDraw.Draw(img), W / 2, H / 2, min(W, H) * frac, fg)
    return img.resize((w, h), Image.LANCZOS)


def speichern(img, pfad, rgb=True):
    os.makedirs(os.path.dirname(pfad) or ".", exist_ok=True)
    (img.convert("RGB") if rgb else img).save(pfad, optimize=True)


def rund(img):
    m = Image.new("L", img.size, 0)
    ImageDraw.Draw(m).ellipse((0, 0, img.size[0] - 1, img.size[1] - 1), fill=255)
    out = Image.new("RGBA", img.size, (0, 0, 0, 0))
    out.paste(img, (0, 0), m)
    return out


# Web / PWA
for sz in (192, 512):
    speichern(bild(sz, sz), f"koch-web/public/icon-{sz}.png")
speichern(bild(512, 512, frac=0.40), "koch-web/public/icon-maskable-512.png")
speichern(bild(180, 180), "koch-web/public/apple-touch-icon.png")
speichern(bild(1200, 630, frac=0.35), "koch-web/public/og-image.png")

# Quellbilder für @capacitor/assets
speichern(bild(1024, 1024), "koch-web/assets/icon.png")
speichern(bild(2732, 2732, frac=0.2), "koch-web/assets/splash.png")
speichern(bild(2732, 2732, bg=BG_DARK, frac=0.2), "koch-web/assets/splash-dark.png")

# Marken-Ordner (Referenzgrößen)
speichern(bild(1024, 1024), "brand/icons/icon-1024.png")
for sz in (32, 48):
    speichern(bild(sz, sz, frac=0.62), f"brand/icons/favicon-{sz}.png")

# Android: vorhandene Dateien in gleicher Größe überschreiben
res = "koch-web/android/app/src/main/res"
for p in glob.glob(f"{res}/mipmap-*/ic_launcher*.png"):
    w, h = Image.open(p).size
    name = os.path.basename(p)
    if name == "ic_launcher_background.png":
        speichern(Image.new("RGB", (w, h), BG), p)
    elif name == "ic_launcher_foreground.png":
        speichern(bild(w, h, frac=0.36, transparent=True), p, rgb=False)
    elif name == "ic_launcher_round.png":
        speichern(rund(bild(w, h)), p, rgb=False)
    else:
        speichern(bild(w, h), p)
for p in glob.glob(f"{res}/drawable*/splash.png"):
    w, h = Image.open(p).size
    speichern(bild(w, h, bg=BG_DARK if "night" in p else BG, frac=0.3), p)

print("Platzhalter erzeugt")
