"""FastAPI web server application for ThetaGuard status console and API routes.

When ENABLE_TRADING_DAEMON=true (the default for cloud deployment), the FastAPI
lifespan launches an asyncio background task that runs the exact same cycle
function the CLI daemon uses.  This ensures one process, one state file, one
source of truth — no separate CLI daemon is needed (or allowed) in parallel.
"""
import asyncio
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from config.calendar_events import get_active_or_upcoming_lockouts, is_time_in_lockout
from config.settings import get_settings
from src.api.routes import router, engine
from src.utils.logger import log

settings = get_settings()
static_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "static")


# ---------------------------------------------------------------------------
# Embedded Trading Daemon (asyncio background task)
# ---------------------------------------------------------------------------

async def _trading_daemon_loop():
    """Mirrors the CLI daemon loop but runs inside the FastAPI event loop.

    Uses the *same* singleton ``engine`` instance that the API routes read from,
    guaranteeing the dashboard always reflects the latest cycle output without
    any state-file synchronisation issues.
    """
    log.info("[EMBEDDED DAEMON] Trading daemon started inside FastAPI process.")
    while True:
        try:
            now = datetime.now(timezone.utc)
            log.info(f"[EMBEDDED DAEMON] Starting cycle at {now.isoformat()}")

            # run_cycle is CPU-bound + network I/O; offload to a thread so the
            # event loop stays responsive for dashboard HTTP requests.
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, engine.run_cycle)

            log.info("[EMBEDDED DAEMON] Cycle completed successfully.")
        except Exception as exc:
            # Never let one bad cycle crash the daemon — log and retry next interval.
            log.error(f"[EMBEDDED DAEMON] Cycle failed with error: {exc}", exc_info=True)

        # Dynamic polling interval (same logic as CLI runner)
        interval_secs = _get_dynamic_interval()
        log.info(f"[EMBEDDED DAEMON] Next cycle in {interval_secs}s")
        await asyncio.sleep(interval_secs)


def _get_dynamic_interval() -> int:
    """Compute the next polling interval (mirrors CLI runner logic)."""
    now = datetime.now(timezone.utc)
    in_lockout, active_event, _ = is_time_in_lockout(now)

    if in_lockout:
        return settings.event_window_polling_seconds  # 30s during macro windows

    upcoming = get_active_or_upcoming_lockouts(now, hours_ahead=2.0)
    if upcoming:
        return settings.event_window_polling_seconds  # 30s approaching events

    return settings.daemon_interval_seconds  # 300s baseline


# ---------------------------------------------------------------------------
# FastAPI Lifespan — conditionally starts the embedded daemon
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    port = int(os.getenv("PORT", settings.app_port))
    log.info(
        f"ThetaGuard Server Started on http://{settings.app_host}:{port} "
        f"[Paper Trading: {settings.alpaca_paper_trade}]"
    )

    daemon_task = None
    if settings.enable_trading_daemon:
        log.info(
            "[LIFESPAN] ENABLE_TRADING_DAEMON=true — launching embedded trading loop. "
            "Do NOT run a separate CLI daemon against the same Alpaca account."
        )
        daemon_task = asyncio.create_task(_trading_daemon_loop())
    else:
        log.info(
            "[LIFESPAN] ENABLE_TRADING_DAEMON=false — dashboard-only mode. "
            "A separate CLI daemon must run the trading loop."
        )

    yield  # FastAPI serves requests while daemon runs in background

    # Shutdown: cancel daemon gracefully
    if daemon_task is not None:
        daemon_task.cancel()
        try:
            await daemon_task
        except asyncio.CancelledError:
            log.info("[LIFESPAN] Embedded trading daemon shut down cleanly.")


# ---------------------------------------------------------------------------
# Application Factory
# ---------------------------------------------------------------------------

app = FastAPI(
    title="ThetaGuard — Alpaca Options Overlay Agent",
    description="Systematic Event-Aware Options Premium Selling Agent for SPY and QQQ",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS middleware for development and external embedding flexibility
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Health check for cloud deployment platforms (Railway, Render, Fly.io, Cloud Run)
@app.get("/health")
def health_check():
    return JSONResponse(
        content={
            "status": "healthy",
            "service": "ThetaGuard Options Overlay Agent",
            "read_only": settings.public_read_only_mode,
            "daemon_enabled": settings.enable_trading_daemon,
        }
    )


# Include API router (/api/status, /api/positions, /api/risk, /api/volatility-history, etc.)
app.include_router(router)


# Root and static asset handlers
@app.get("/")
def serve_index():
    index_path = os.path.join(static_dir, "index.html")
    return FileResponse(index_path, headers={"Cache-Control": "no-cache"})


@app.get("/style.css")
def serve_css():
    css_path = os.path.join(static_dir, "style.css")
    return FileResponse(css_path, media_type="text/css", headers={"Cache-Control": "no-cache"})


@app.get("/app.js")
def serve_js():
    js_path = os.path.join(static_dir, "app.js")
    return FileResponse(js_path, media_type="application/javascript", headers={"Cache-Control": "no-cache"})


@app.get("/assets/logo.jpg")
def serve_logo():
    logo_path = os.path.join(static_dir, "assets", "logo.jpg")
    return FileResponse(logo_path, media_type="image/jpeg", headers={"Cache-Control": "public, max-age=86400"})


@app.get("/assets/bg.jpg")
def serve_bg():
    bg_path = os.path.join(static_dir, "assets", "bg.jpg")
    return FileResponse(bg_path, media_type="image/jpeg", headers={"Cache-Control": "public, max-age=86400"})


assets_dir = os.path.join(static_dir, "assets")
if os.path.exists(assets_dir):
    app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

if os.path.exists(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", settings.app_port))
    uvicorn.run("src.api.main:app", host=settings.app_host, port=port, reload=False)
