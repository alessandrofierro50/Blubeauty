"""Salvataggio e pubblicazione delle immagini. Ogni immagine viene ridimensionata e convertita in WebP,
con una miniatura. I nomi dei file sono casuali (non indovinabili), quindi possono essere serviti senza token
e usati direttamente nei tag <img> e nei PDF."""

import io
import os
import re
import uuid

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import FileResponse
from PIL import Image, ImageOps, UnidentifiedImageError

from app.core.config import get_settings

MAX_BYTES = 8 * 1024 * 1024
FULL_SIZE = 1600
THUMB_SIZE = 400

router = APIRouter(prefix="/api/media", tags=["media"])
_NAME = re.compile(r"^[0-9a-f]{32}(_t)?\.webp$")
_FILE = re.compile(r"^[0-9a-f]{32}\.(pdf|docx|xlsx|doc|xls|jpg|jpeg|png|webp|txt|zip|xml)$")
FILE_TYPES = {"pdf": "application/pdf", "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
              "doc": "application/msword", "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
              "xls": "application/vnd.ms-excel", "jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png",
              "webp": "image/webp", "txt": "text/plain", "zip": "application/zip", "xml": "application/xml"}
MAX_FILE = 20 * 1024 * 1024


def media_dir() -> str:
    path = get_settings().media_dir
    os.makedirs(path, exist_ok=True)
    return path


def save_image(data: bytes) -> str:
    """Restituisce il nome base del file salvato (senza estensione)."""
    if len(data) > MAX_BYTES:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "Immagine troppo grande (massimo 8 MB)")
    try:
        img = Image.open(io.BytesIO(data))
        img = ImageOps.exif_transpose(img)  # foto da smartphone: orientamento corretto
        img.load()
    except (UnidentifiedImageError, OSError):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "File non riconosciuto come immagine") from None
    if img.mode not in ("RGB", "RGBA"):
        img = img.convert("RGBA" if "A" in img.getbands() else "RGB")
    name = uuid.uuid4().hex
    base = media_dir()
    full = img.copy()
    full.thumbnail((FULL_SIZE, FULL_SIZE))
    full.save(os.path.join(base, f"{name}.webp"), "WEBP", quality=85)
    thumb = img.copy()
    thumb.thumbnail((THUMB_SIZE, THUMB_SIZE))
    thumb.save(os.path.join(base, f"{name}_t.webp"), "WEBP", quality=80)
    return name


def delete_image(name: str) -> None:
    for suffix in ("", "_t"):
        try:
            os.remove(os.path.join(media_dir(), f"{name}{suffix}.webp"))
        except FileNotFoundError:
            pass


def urls(name: str) -> dict:
    return {"url": f"/api/media/{name}.webp", "thumb_url": f"/api/media/{name}_t.webp"}


@router.get("/{file_name}")
def serve(file_name: str):
    if not _NAME.match(file_name):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "File non trovato")
    path = os.path.join(media_dir(), file_name)
    if not os.path.exists(path):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "File non trovato")
    return FileResponse(path, media_type="image/webp", headers={"Cache-Control": "public, max-age=31536000, immutable"})


def save_file(data: bytes, original_name: str) -> str:
    """Salva un documento (PDF, Office, immagini...). Restituisce il nome del file salvato."""
    ext = (original_name.rsplit(".", 1)[-1] if "." in original_name else "").lower()
    if ext not in FILE_TYPES:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Tipo di file non ammesso (PDF, Word, Excel, immagini)")
    if len(data) > MAX_FILE:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "File troppo grande (massimo 20 MB)")
    if ext == "pdf" and not data.startswith(b"%PDF"):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Il file non è un PDF valido")
    name = f"{uuid.uuid4().hex}.{ext}"
    with open(os.path.join(media_dir(), name), "wb") as fh:
        fh.write(data)
    return name


def delete_file(name: str) -> None:
    try:
        os.remove(os.path.join(media_dir(), name))
    except FileNotFoundError:
        pass


@router.get("/file/{file_name}")
def serve_file(file_name: str, n: str | None = None):
    if not _FILE.match(file_name):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "File non trovato")
    path = os.path.join(media_dir(), file_name)
    if not os.path.exists(path):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "File non trovato")
    ext = file_name.rsplit(".", 1)[-1]
    safe = re.sub(r'[^A-Za-z0-9 ._()-]', "_", n or file_name)[:150]
    return FileResponse(path, media_type=FILE_TYPES[ext], headers={"Content-Disposition": f'inline; filename="{safe}"',
                                                                    "Cache-Control": "private, max-age=86400"})
