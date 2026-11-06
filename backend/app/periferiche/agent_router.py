"""API per BluBeauty Agent: /api/agent/...  (autenticazione col token dell'agent, header "Authorization: Agent <token>").

L'agent apre lui la connessione (niente porte da aprire nel negozio) e resta in attesa fino a 25 secondi che arrivi
un lavoro: così uno scontrino parte in meno di un secondo senza tempestare il server di richieste."""

import asyncio
import uuid

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.core.db import get_db, new_session
from app.periferiche import service as per
from app.saas.logic import blocked_code
from app.saas.service import load_tenant, tenant_state

router = APIRouter(prefix="/api/agent", tags=["agent"])


def _token(authorization: str | None) -> str | None:
    if authorization and authorization.lower().startswith("agent "):
        return authorization[6:].strip()
    return None


def _check_tenant(db: Session, agent) -> None:
    st = tenant_state(load_tenant(db, agent.tenant_id))
    if st.access == "none":
        raise HTTPException(status.HTTP_402_PAYMENT_REQUIRED,
                            {"code": blocked_code(st.status), "message": "Abbonamento sospeso o scaduto"})
    if "periferiche" not in st.modules:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Le periferiche non sono incluse nel pacchetto")


def agent_dep(authorization: str | None = Header(None), db: Session = Depends(get_db)):
    agent = per.agent_from_token(db, _token(authorization))
    _check_tenant(db, agent)
    return agent, db


class PairIn(BaseModel):
    code: str = Field(min_length=6, max_length=12)
    hostname: str | None = None
    version: str | None = None
    platform: str | None = None


@router.post("/abbina")
def pair(body: PairIn, db: Session = Depends(get_db)):
    return per.pair(db, body.code, body.model_dump())


@router.get("/configurazione")
def configuration(dep=Depends(agent_dep)):
    agent, db = dep
    agent.last_seen_at = per.now()
    return per.agent_config(db, agent)


def _claim_once(token: str) -> list[dict]:
    db = new_session()
    try:
        agent = per.agent_from_token(db, token)
        _check_tenant(db, agent)
        jobs = per.claim(db, agent)
        db.commit()
        return jobs
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


@router.get("/lavori")
async def jobs(attesa: int = Query(25, ge=0, le=30), authorization: str | None = Header(None)):
    token = _token(authorization)
    loop = asyncio.get_running_loop()
    deadline = loop.time() + attesa
    while True:
        found = await run_in_threadpool(_claim_once, token)
        if found or loop.time() >= deadline:
            return found
        await asyncio.sleep(0.5)


class ResultIn(BaseModel):
    ok: bool
    result: dict | None = None
    error: str | None = Field(None, max_length=2000)


@router.post("/lavori/{job_id}/esito")
def job_result(job_id: uuid.UUID, body: ResultIn, dep=Depends(agent_dep)):
    agent, db = dep
    j = per.complete(db, agent, job_id, body.ok, body.result, body.error)
    return {"id": str(j.id), "status": j.status}


class ProgressIn(BaseModel):
    progress: dict = {}


@router.post("/lavori/{job_id}/avanzamento")
def job_progress(job_id: uuid.UUID, body: ProgressIn, dep=Depends(agent_dep)):
    """Avanzamento dei lavori lunghi (cassa automatica): la risposta porta l'annullamento chiesto (0, 1 parziale, 2 restituisci)."""
    agent, db = dep
    return {"cancel": per.progress(db, agent, job_id, body.progress)}
