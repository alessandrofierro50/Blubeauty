"""Video esplicativi di BluBeauty: per ogni tema copertina + schermate con zoom lento + voce + sottotitoli (.srt)."""
import asyncio, json, math, os, re, subprocess, sys

import certifi
certifi.where = lambda: "/root/.ccr/ca-bundle.crt"  # proxy della sessione
import edge_tts
from PIL import Image, ImageDraw, ImageFilter, ImageFont

SP = "/tmp/claude-0/-home-user/a3d1293f-40b5-5d44-9ac8-a23fb5328f2b/scratchpad"
VD, SHOTS = f"{SP}/video2", f"{SP}/shots"
VOICE, RATE = sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "+0%"
ONLY = sys.argv[3].split(",") if len(sys.argv) > 3 else None
W, H, FPS = 1920, 1080, 30
FONTS = "/home/user/blubeauty/frontend/node_modules/@fontsource"
F_TITLE = f"{FONTS}/archivo/files/archivo-latin-800-normal.woff"
F_TEXT = f"{FONTS}/source-sans-3/files/source-sans-3-latin-400-normal.woff"
F_SEMI = f"{FONTS}/source-sans-3/files/source-sans-3-latin-600-normal.woff"
LOGO = "/home/user/blubeauty/frontend/public/brand/blubeauty-icon-512.png"
DARK, BLUE, LIGHT, GOLD = (11, 33, 71), (35, 64, 168), (110, 193, 228), (242, 180, 19)

def run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError(r.stderr[-1500:])
    return r.stdout

def duration(path):
    return float(run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path]).strip())

def gradient(w, h, top, bottom):
    g = Image.new("RGB", (1, h))
    for y in range(h):
        t = y / (h - 1)
        g.putpixel((0, y), tuple(int(top[i] + (bottom[i] - top[i]) * t) for i in range(3)))
    return g.resize((w, h))

def title_card(path, n, total, title, subtitle):
    im = gradient(W, H, DARK, BLUE)
    d = ImageDraw.Draw(im)
    for i in range(6):  # cerchi morbidi decorativi
        d.ellipse((1400 - i * 60, -300 + i * 40, 2300 - i * 60, 600 + i * 40), outline=(255, 255, 255, 0), width=1)
    logo = Image.open(LOGO).convert("RGBA").resize((170, 170))
    im.paste(logo, (160, 250), logo)
    d.text((360, 290), "BluBeauty", font=ImageFont.truetype(F_TITLE, 60), fill="white")
    d.text((362, 368), "Guida rapida · BluCode Informatica", font=ImageFont.truetype(F_TEXT, 32), fill=LIGHT)
    d.rectangle((160, 500, 300, 508), fill=GOLD)
    d.text((160, 540), f"Capitolo {n} di {total}", font=ImageFont.truetype(F_SEMI, 36), fill=LIGHT)
    d.text((160, 600), title, font=ImageFont.truetype(F_TITLE, 96), fill="white")
    d.text((162, 730), subtitle, font=ImageFont.truetype(F_TEXT, 46), fill=(220, 230, 250))
    im.save(path)

def phone_frame(src, path):
    bg = gradient(W, H, (236, 241, 252), (214, 226, 248))
    sh = Image.open(src).convert("RGB")
    ph_h = 980
    ph_w = int(sh.width * ph_h / sh.height)
    sh = sh.resize((ph_w, ph_h))
    pad = 22
    frame = Image.new("RGBA", (ph_w + 2 * pad, ph_h + 2 * pad), (0, 0, 0, 0))
    fd = ImageDraw.Draw(frame)
    fd.rounded_rectangle((0, 0, frame.width - 1, frame.height - 1), radius=64, fill=(20, 22, 28, 255))
    mask = Image.new("L", sh.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, ph_w - 1, ph_h - 1), radius=44, fill=255)
    frame.paste(sh, (pad, pad), mask)
    shadow = Image.new("RGBA", (frame.width + 120, frame.height + 120), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle((60, 80, frame.width + 60, frame.height + 60), radius=64, fill=(10, 30, 80, 90))
    shadow = shadow.filter(ImageFilter.GaussianBlur(30))
    x, y = (W - frame.width) // 2, (H - frame.height) // 2
    bg.paste(shadow, (x - 60, y - 60), shadow)
    bg.paste(frame, (x, y), frame)
    bg.save(path)

def fit_frame(src, path):
    bg = Image.new("RGB", (W, H), "white")
    im = Image.open(src).convert("RGB")
    s = min((W - 80) / im.width, (H - 80) / im.height)
    im = im.resize((int(im.width * s), int(im.height * s)))
    bg.paste(im, ((W - im.width) // 2, (H - im.height) // 2))
    bg.save(path)

async def tts(text, out):
    await edge_tts.Communicate(text, VOICE, rate=RATE).save(out)

def clip(img, audio, out, zoom=1.0, focus=(0.5, 0.5)):
    """Immagine con zoom lento verso il punto indicato, voce con piccole pause prima e dopo, dissolvenze."""
    d = duration(audio) + 0.9
    n = math.ceil(d * FPS)
    fx, fy = focus
    z = f"min(1+({zoom}-1)*on/{max(n - 1, 1)},{zoom})"
    vf = (f"scale={2 * W}:{2 * H},zoompan=z='{z}':x='max(0,min(iw-iw/zoom,iw*{fx}-iw/zoom/2))':"
          f"y='max(0,min(ih-ih/zoom,ih*{fy}-ih/zoom/2))':d={n}:s={W}x{H}:fps={FPS},"
          f"fade=t=in:st=0:d=0.3,fade=t=out:st={d - 0.35:.2f}:d=0.35,format=yuv420p")
    run(["ffmpeg", "-y", "-loop", "1", "-i", img, "-i", audio, "-filter_complex",
         f"[0:v]{vf}[v];[1:a]adelay=350|350,apad=pad_dur=1,aresample=48000[a]", "-map", "[v]", "-map", "[a]",
         "-t", f"{d:.2f}", "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-c:a", "aac", "-b:a", "160k", "-ac", "2", out])
    return d

def srt_time(t):
    h, rem = divmod(t, 3600); m, s = divmod(rem, 60)
    return f"{int(h):02d}:{int(m):02d}:{int(s):02d},{int(round((s - int(s)) * 1000)):03d}"

def chunks(text):
    """Sottotitoli a frasi brevi (max ~90 caratteri)."""
    parts = re.split(r"(?<=[.!?:])\s+", text)
    out = []
    for p in parts:
        while len(p) > 90:
            cut = p.rfind(",", 0, 90)
            cut = cut if cut > 30 else p.rfind(" ", 0, 90)
            out.append(p[:cut + 1].strip()); p = p[cut + 1:].strip()
        if p:
            out.append(p)
    return out

def build(theme, n, total):
    tid = theme["id"]
    wd = f"{VD}/tmp/{tid}"
    os.makedirs(wd, exist_ok=True)
    items = [{"img": None, "text": f"{theme['title']}.", "card": True}] + theme["scenes"]
    clips, subs, t = [], [], 0.0
    for i, sc in enumerate(items):
        img = f"{wd}/img{i:02d}.png"
        if sc.get("card"):
            title_card(img, n, total, theme["title"], theme["subtitle"])
        elif theme.get("phone"):
            phone_frame(f"{SHOTS}/{sc['img']}.png", img)
        elif sc.get("fit"):
            fit_frame(f"{SHOTS}/{sc['img']}.png", img)
        else:
            img = f"{SHOTS}/{sc['img']}.png"
        audio = f"{wd}/a{i:02d}.mp3"
        asyncio.run(tts(sc["text"], audio))
        out = f"{wd}/c{i:02d}.mp4"
        zoom = 1.0 if sc.get("card") or theme.get("phone") or sc.get("fit") else sc.get("zoom", 1.08)
        d = clip(img, audio, out, zoom, tuple(sc.get("focus", (0.5, 0.5))))
        if not sc.get("card"):
            ch = chunks(sc["text"])
            speak = d - 0.9
            tot = sum(len(c) for c in ch)
            s0 = t + 0.35
            for c in ch:
                dur = speak * len(c) / tot
                subs.append((s0, s0 + dur, c)); s0 += dur
        clips.append(out); t += d
    lst = f"{wd}/list.txt"
    open(lst, "w").write("".join(f"file '{c}'\n" for c in clips))
    final = f"{VD}/out/BluBeauty-{tid}.mp4"
    os.makedirs(f"{VD}/out", exist_ok=True)
    run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", lst, "-c", "copy", "-movflags", "+faststart", final])
    with open(final[:-4] + ".srt", "w", encoding="utf-8") as f:
        for k, (a, b, c) in enumerate(subs, 1):
            f.write(f"{k}\n{srt_time(a)} --> {srt_time(b)}\n{c}\n\n")
    print(f"{tid}: {t:.1f} s", flush=True)
    return final

themes = json.load(open(f"{VD}/temi.json"))
outs = []
for n, th in enumerate(themes, 1):
    if ONLY and th["id"] not in ONLY:
        continue
    outs.append(build(th, n, len(themes)))
