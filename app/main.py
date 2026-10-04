import logging
import socket
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.config import STATIC_DIR, get_settings
from app.db import init_db
from app.routes import demo, review, sms, voice

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("app")


def _cli_opt(name: str, default: str) -> str:
    """Read --name value / --name=value from the uvicorn command line."""
    args = sys.argv[1:]
    for i, a in enumerate(args):
        if a == name and i + 1 < len(args):
            return args[i + 1]
        if a.startswith(name + "="):
            return a.split("=", 1)[1]
    return default


def _lan_ip() -> str | None:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))  # no packet sent; picks the outbound interface
            return s.getsockname()[0]
    except OSError:
        return None


def _log_links() -> None:
    host = _cli_opt("--host", "127.0.0.1")
    port = _cli_opt("--port", "8000")
    bases = [f"http://localhost:{port}"]
    if host in ("0.0.0.0", "::") and (ip := _lan_ip()):
        bases.append(f"http://{ip}:{port}")
    elif host not in ("127.0.0.1", "localhost"):
        bases.append(f"http://{host}:{port}")
    elif ip := _lan_ip():
        log.info("network link http://%s:%s/demo needs: uvicorn app.main:app --host 0.0.0.0 --port %s", ip, port, port)
    public = get_settings().public_base_url.rstrip("/")
    if public and "localhost" not in public and "127.0.0.1" not in public and public not in bases:
        bases.append(public)
    for base in bases:
        log.info("demo: %s/demo   review: %s/review", base, base)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    _log_links()
    if get_settings().whisper_preload:
        import threading

        from app.pipeline.stt import preload

        threading.Thread(target=preload, daemon=True).start()
    yield


app = FastAPI(title="Shamba Call", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
app.include_router(demo.router)
app.include_router(review.router)
app.include_router(voice.router)
app.include_router(sms.router)


@app.get("/health")
def health(deep: bool = False) -> dict:
    if not deep:
        return {"status": "ok"}
    from app.health import deep_health

    return {"status": "ok", **deep_health()}


@app.get("/", include_in_schema=False)
def index():
    return RedirectResponse("/demo")
