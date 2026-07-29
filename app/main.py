"""
FastAPI application entry point
"""
import os
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
import starlette.middleware.gzip

# Skip gzip for image/* — already compressed, CPU waste for ~0% gain
starlette.middleware.gzip.DEFAULT_EXCLUDED_CONTENT_TYPES = ("text/event-stream", "image/")

from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from app.routers import api
from app.routers import sync as sync_router
from app.cache import sync_manifest, get_images_directory

app = FastAPI(
    title="ViewMaster API",
    description="A FastAPI web application",
    version="1.0.0",
    docs_url=None,  # Disable Swagger UI
    redoc_url=None,  # Disable ReDoc
    openapi_url=None,  # Disable OpenAPI schema endpoint
)

@app.on_event("startup")
async def startup_event():
    """Load existing manifest on startup. If missing, run incremental sync."""
    try:
        from app.cache import load_manifest

        images_dir = get_images_directory()
        if images_dir.exists() and images_dir.is_dir():
            # Try to load existing manifest from disk
            loaded = load_manifest()
            # If no manifest on disk, perform an initial incremental sync
            if loaded is None:
                sync_manifest(images_dir)
    except Exception as e:
        print(f"Warning: Failed to sync manifest on startup: {e}")

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure appropriately for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Configure compression - compress responses larger than 1000 bytes
app.add_middleware(GZipMiddleware, minimum_size=1000)

# Include API router
app.include_router(api.router)

# Include sync WebSocket router
app.include_router(sync_router.router)

# Images are now served through authenticated endpoints in the API router

# Mount static files directory
static_dir = Path(__file__).parent.parent / "static"
if static_dir.exists():
    # Mount assets directory (JS, CSS files from Vite build)
    assets_dir = static_dir / "assets"
    if assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")

    # Mount root static files (favicon, etc.)
    # Serve files from static root, but exclude index.html (handled by catch-all)
    static_files = StaticFiles(directory=str(static_dir), html=False)
    app.mount("/static", static_files, name="static")


# SPA catch-all route - must be last
@app.get("/{full_path:path}")
async def serve_spa(request: Request, full_path: str):
    """
    Serve the Svelte SPA for all non-API routes.
    This allows client-side routing to work properly.
    """
    # Don't interfere with API routes or static assets
    if (
        full_path.startswith("api/")
        or full_path.startswith("assets/")
        or full_path.startswith("static/")
    ):
        return {"error": "Not found"}

    # Serve index.html for SPA routing
    index_path = static_dir / "index.html"
    if index_path.exists():
        return FileResponse(str(index_path))

    return {"error": "Frontend not built. Run 'npm run build' in the frontend directory."}