import os
from fontTools.ttLib import TTFont
from fontTools.varLib.instancer import instantiateVariableFont
from PIL import Image, ImageDraw, ImageFont

SRC = "../koch-web/node_modules/@fontsource-variable/fraunces/files/fraunces-latin-full-normal.woff2"
STATIC = "fraunces-display.ttf"

# Variable -> statische Display-Schrift (große optische Größe, halbfett)
ft = TTFont(SRC)  # woff2 via brotli
axes = {a.axisTag:(a.minValue,a.defaultValue,a.maxValue) for a in ft["fvar"].axes}
want = {}
for tag, val in {"opsz":144, "wght":600, "SOFT":0, "WONK":0}.items():
    if tag in axes: want[tag] = val
instantiateVariableFont(ft, want, inplace=True)
ft.flavor = None
ft.save(STATIC)
print("axes:", list(axes), "-> instanced", want)

TERRA=(192,73,47); PAPER=(251,246,236); INK=(43,34,24); OLIVE=(107,112,68); BUTTER=(232,176,75)
SANS="/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"

def fnt(sz): return ImageFont.truetype(STATIC, sz)
def sans(sz): return ImageFont.truetype(SANS, sz)

def draw_S(d, box, font, fill):
    x0,y0,x1,y1=box
    l,t,r,b=d.textbbox((0,0),"S",font=font)
    w,h=r-l,b-t
    cx,cy=(x0+x1)//2,(y0+y1)//2
    d.text((cx-w//2-l, cy-h//2-t),"S",font=font,fill=fill)

def icon(size, bg, fg, frac=0.60, spark=True, ss=4):
    """gerendert mit Supersampling fuer glatte Kanten"""
    S=size*ss
    img=Image.new("RGB",(S,S),bg); d=ImageDraw.Draw(img)
    draw_S(d,(0,0,S,S),fnt(int(S*frac)),fg)
    if spark:
        r=int(S*0.066); cx,cy=int(S*0.705),int(S*0.275)
        d.ellipse((cx-r,cy-r,cx+r,cy+r),fill=BUTTER)
    return img.resize((size,size),Image.LANCZOS)

def rounded(img,rad,bg=PAPER):
    m=Image.new("L",img.size,0)
    ImageDraw.Draw(m).rounded_rectangle((0,0,img.size[0]-1,img.size[1]-1),rad,fill=255)
    out=Image.new("RGB",img.size,bg); out.paste(img,(0,0),m); return out

os.makedirs("icons",exist_ok=True)

# --- Live-Icon-Familie (echte Dateien) ---
# Voll ausgefuelltes Tile (App-Store/Android adaptive uebernimmt Rundung)
master=icon(1024,TERRA,PAPER,frac=0.60,spark=True)
master.save("icons/icon-1024.png")
for sz in (512,192):
    icon(sz,TERRA,PAPER,frac=0.60).save(f"icons/icon-{sz}.png")
# apple-touch (gerundet, kein Alpha)
rounded(icon(180,TERRA,PAPER,frac=0.60),40).save("icons/apple-touch-icon.png")
# maskable: mehr Sicherheitsrand -> S kleiner, Hintergrund voll
icon(512,TERRA,PAPER,frac=0.46,spark=True).save("icons/icon-maskable-512.png")
# favicon
icon(48,TERRA,PAPER,frac=0.62,spark=False).save("icons/favicon-48.png")
icon(32,TERRA,PAPER,frac=0.62,spark=False).save("icons/favicon-32.png")

print("done")
