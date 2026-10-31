# Wrapper edge-tts che usa il CA bundle del proxy (certifi.where → bundle di sistema del proxy)
import sys, asyncio, certifi
# Nel container di sviluppo il traffico passa da un proxy con CA propria
import os
if os.path.exists("/root/.ccr/ca-bundle.crt"):
    certifi.where = lambda: "/root/.ccr/ca-bundle.crt"
import edge_tts
voice, rate, text_file, out = sys.argv[1:5]
text = open(text_file, encoding="utf-8").read()
async def main():
    await edge_tts.Communicate(text, voice, rate=rate).save(out)
asyncio.run(main())
