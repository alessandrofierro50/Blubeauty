# Video dimostrativo BluBeauty

Genera il video con commento parlato (voce femminile italiana) che mostra il percorso completo:
prenotazione da smartphone → conferma/disdetta WhatsApp → agenda → cassa → scontrino / fattura → marketing.

Requisiti: app in esecuzione su `http://localhost:3100` con i dati demo, `ffmpeg`, Playwright, Python con `edge-tts`.

```bash
# 1. dati demo puliti e server (link dei messaggi sul dominio reale)
SEED_RESET=1 APP_URL=https://blubeauty.blucodeinformatica.it TZ=Europe/Rome npx prisma db seed
npm run build && APP_URL=https://blubeauty.blucodeinformatica.it PORT=3100 TZ=Europe/Rome npm start

# 2. voce (testi in scenes.json)
pip install edge-tts
mkdir -p tools/video-demo/audio
python3 -c "import json;[open(f'tools/video-demo/audio/{s[\"id\"]}.txt','w').write(s['text']) for s in json.load(open('tools/video-demo/scenes.json'))]"
for f in tools/video-demo/audio/*.txt; do python3 tools/video-demo/tts.py it-IT-IsabellaNeural -3% "$f" "${f%.txt}.mp3"; done

# 3. registrazione delle scene (1920x1080) e montaggio
node tools/video-demo/record.js
python3 tools/video-demo/assemble.py
```

Per modificare il commento basta cambiare i testi in `scenes.json`: ogni scena si adatta alla durata della voce.
`tts.py` usa il CA bundle del proxy del container di sviluppo: fuori da quell'ambiente si può usare direttamente `edge-tts`.
