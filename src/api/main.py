"""FastAPI web server application for ThetaGuard status console and API routes."""
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from config.settings import get_settings
from src.api.routes import router
from src.utils.logger import log

settings = get_settings()
static_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "static")


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info(
        f"ThetaGuard Server Started on http://{settings.app_host}:{settings.app_port} "
        f"[Paper Trading: {settings.alpaca_paper_trade}]"
    )
    yield


app = FastAPI(
    title="ThetaGuard — Alpaca Options Overlay Agent",
    description="Systematic Event-Aware Options Premium Selling Agent for SPY and QQQ",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS middleware for development flexibility
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include API router (/api/status, /api/positions, /api/risk, etc.)
app.include_router(router)


# Root and static asset handlers
@app.get("/")
def serve_index():
    index_path = os.path.join(static_dir, "index.html")
    return FileResponse(index_path)


@app.get("/style.css")
def serve_css():
    css_path = os.path.join(static_dir, "style.css")
    return FileResponse(css_path, media_type="text/css")


@app.get("/app.js")
def serve_js():
    js_path = os.path.join(static_dir, "app.js")
    return FileResponse(js_path, media_type="application/javascript")


@app.get("/assets/logo.jpg")
def serve_logo():
    logo_path = os.path.join(static_dir, "assets", "logo.jpg")
    return FileResponse(logo_path, media_type="image/jpeg")


@app.get("/assets/bg.jpg")
def serve_bg():
    bg_path = os.path.join(static_dir, "assets", "bg.jpg")
    return FileResponse(bg_path, media_type="image/jpeg")


assets_dir = os.path.join(static_dir, "assets")
if os.path.exists(assets_dir):
    app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

if os.path.exists(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("src.api.main:app", host=settings.app_host, port=settings.app_port, reload=True)
