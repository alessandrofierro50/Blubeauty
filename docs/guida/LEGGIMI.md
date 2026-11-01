# Guida di BluBeauty: manuale PDF e video

Generatori del **manuale d'uso** (PDF con indice cliccabile) e dei **video esplicativi per temi** (voce femminile,
sottotitoli `.srt`). Usano le stesse schermate, prese dal programma con i dati dimostrativi.

1. Avviare BluBeauty in locale con i dati demo (`SEED_DEMO=1`), API su 8000 e interfaccia su 3300.
2. `demo_periferiche.py` (registratore e stampante simulati + agent abbinato) e `demo_apri_cassa.py` (apre la cassa).
3. `node schermate.js <cartella> <id cassa>`: 35 schermate (martedì 3 novembre 2026 ore 10:20 con l'orologio finto del
   browser; prenotazione online su telefono 390×844). Più `anteprima.png` della ricevuta non fiscale.
4. `python manuale_pdf.py <out.pdf>`: ReportLab, caratteri Archivo e Source Sans 3 (convertiti da @fontsource con fontTools).
5. `python video.py <voce> [velocità] [temi]`: testi in `video_temi.json`; voce con edge-tts (es. `it-IT-IsabellaNeural`,
   `en-US-AvaMultilingualNeural`); ffmpeg con zoom lento sul punto `focus`; copertina per capitolo; `.srt` per tema.

I percorsi in cima agli script puntano alla cartella di lavoro della sessione in cui sono stati creati: adattarli.
