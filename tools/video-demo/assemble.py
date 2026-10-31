# Monta il video finale: voce + video per scena, dissolvenze, concatenazione, sottotitoli, loudness.
# Uso: python3 assemble.py   (dopo tts e record.js)
import json, os, re, subprocess

V = os.path.dirname(os.path.abspath(__file__))
scenes = json.load(open(f"{V}/scenes.json"))
os.makedirs(f"{V}/seg", exist_ok=True)
DELAY = 0.25


def dur(f):
    return float(subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", f]).decode())


def ts(x):
    h, m, s = int(x // 3600), int(x % 3600 // 60), x % 60
    return f"{h:02d}:{m:02d}:{int(s):02d},{int(round((s - int(s)) * 1000)):03d}"


srt, t, n = [], 0.0, 1
with open(f"{V}/seg/list.txt", "w") as lst:
    for s in scenes:
        vid, aud, out = f"{V}/raw/{s['id']}.mp4", f"{V}/audio/{s['id']}.mp3", f"{V}/seg/{s['id']}.mp4"
        L, A = dur(vid), dur(aud)
        subprocess.check_call([
            "ffmpeg", "-v", "error", "-y", "-i", vid, "-i", aud, "-filter_complex",
            f"[0:v]fade=t=in:st=0:d=0.35,fade=t=out:st={L-0.4:.3f}:d=0.4[v];"
            f"[1:a]adelay={int(DELAY*1000)}:all=1,apad,aresample=48000,aformat=channel_layouts=stereo[a]",
            "-map", "[v]", "-map", "[a]", "-t", f"{L:.3f}", "-c:v", "libx264", "-preset", "medium", "-crf", "18",
            "-r", "30", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-ar", "48000", out,
        ])
        lst.write(f"file '{out}'\n")
        chunks = []
        for p in [p.strip() for p in re.split(r"(?<=[.!?:])\s+", s["text"]) if p.strip()]:
            cur = []
            for w in p.split():
                cur.append(w)
                if len(" ".join(cur)) > 70:
                    chunks.append(" ".join(cur))
                    cur = []
            if cur:
                chunks.append(" ".join(cur))
        total, st = sum(len(c) for c in chunks), t + DELAY
        for c in chunks:
            d = A * len(c) / total
            srt.append(f"{n}\n{ts(st)} --> {ts(st + d - 0.05)}\n{c}\n")
            n, st = n + 1, st + d
        t += L

open(f"{V}/BluBeauty-demo.srt", "w").write("\n".join(srt))
subprocess.check_call(["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", f"{V}/seg/list.txt", "-c", "copy", f"{V}/seg/joined.mp4"])
subprocess.check_call([
    "ffmpeg", "-v", "error", "-y", "-i", f"{V}/seg/joined.mp4", "-c:v", "copy",
    "-af", "loudnorm=I=-16:TP=-1.5:LRA=11,aresample=48000", "-c:a", "aac", "-b:a", "192k",
    "-movflags", "+faststart", f"{V}/BluBeauty-demo.mp4",
])
print(f"Video: {V}/BluBeauty-demo.mp4 ({t:.1f}s)")
