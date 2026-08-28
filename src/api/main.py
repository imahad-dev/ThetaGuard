"""FastAPI web server application for ThetaGuard status console and API routes."""
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from config.settings import get_settings
from src.api.routes import router
from src.utils.logger import log

settings = get_settings()
static_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "static")


@asynccontextmanager
async def lifespan(app: FastAPI):
    port = int(os.getenv("PORT", settings.app_port))
    log.info(
        f"ThetaGuard Server Started on http://{settings.app_host}:{port} "
        f"[Paper Trading: {settings.alpaca_paper_trade}]"
    )
    yield


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
