from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.anagrafiche.router import router as anagrafiche_router
from app.auth.router import router as auth_router
from app.core.config import get_settings
from app.core.media import router as media_router
from app.magazzino.router import router as magazzino_router
from app.documenti.acquisti_router import router as acquisti_router
from app.documenti.vendite_router import router as vendite_router
from app.scadenzario.router import router as scadenzario_router
from app.fatturapa.router import callbacks as fatturapa_callbacks
from app.fatturapa.router import router as fatturapa_router
from app.statistiche.router import router as statistiche_router
from app.pos.router import router as pos_router
from app.periferiche.router import router as periferiche_router
from app.periferiche.agent_router import router as agent_router
from app.bi.router import router as bi_router
from app.tentata.router import public as tentata_public
from app.tentata.router import router as tentata_router
from app.pagamenti.router import admin_router as pagamenti_admin_router
from app.pagamenti.router import app_router as pagamenti_app_router
from app.pagamenti.router import public as pagamenti_public
from app.saas.console import router as console_router
from app.saas.public_router import router as public_router
from app.saas.router import router as admin_router
from app.tenant.router import router as app_router

settings = get_settings()

app = FastAPI(title=f"{settings.brand_name} API", version="0.1.0", docs_url="/api/docs", openapi_url="/api/openapi.json")

app.add_middleware(
    CORSMiddleware,
    # il sito blucodeinformatica.it manda il modulo della prova gratuita direttamente a /api/public/prova
    allow_origins=[settings.public_url, "http://localhost:5173", settings.website_url.rstrip("/"),
                   settings.website_url.rstrip("/").replace("https://", "https://www.")],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(admin_router)
app.include_router(public_router)
app.include_router(console_router)
app.include_router(app_router)
app.include_router(anagrafiche_router)
app.include_router(media_router)
app.include_router(magazzino_router)
app.include_router(acquisti_router)
app.include_router(vendite_router)
app.include_router(scadenzario_router)
app.include_router(fatturapa_router)
app.include_router(fatturapa_callbacks)
app.include_router(statistiche_router)
app.include_router(bi_router)
app.include_router(pos_router)
app.include_router(periferiche_router)
app.include_router(agent_router)
app.include_router(tentata_router)
app.include_router(tentata_public)
app.include_router(pagamenti_app_router)
app.include_router(pagamenti_public)
app.include_router(pagamenti_admin_router)


@app.get("/api/health")
def health():
    return {"status": "ok", "product": settings.brand_name}
