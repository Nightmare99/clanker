"""FastAPI application for Clanker configuration."""

import os
import signal
import threading
import webbrowser
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from clanker.config.web.routes import router

# Static files directory (pre-built Vue app)
STATIC_DIR = Path(__file__).parent / "static"


def create_app() -> FastAPI:
    """Create the FastAPI application."""
    app = FastAPI(
        title="Clanker Config",
        description="Web-based configuration for Clanker CLI",
        version="0.1.0",
    )

    # Mount API routes
    app.include_router(router, prefix="/api")

    # Serve static files (Vue app)
    if STATIC_DIR.exists():
        app.mount("/assets", StaticFiles(directory=STATIC_DIR / "assets"), name="assets")

        @app.get("/")
        async def serve_index():
            """Serve the main Vue app."""
            return FileResponse(STATIC_DIR / "index.html")

        @app.get("/{path:path}")
        async def serve_spa(path: str):
            """Serve Vue app for all other routes (SPA routing)."""
            file_path = STATIC_DIR / path
            if file_path.exists() and file_path.is_file():
                return FileResponse(file_path)
            return FileResponse(STATIC_DIR / "index.html")

    return app


def run_config_server(
    port: int = 8765,
    open_browser: bool = True,
    host: str = "127.0.0.1",
) -> None:
    """Run the configuration web server.

    Args:
        port: Port to run the server on.
        open_browser: Whether to open browser automatically.
        host: Host to bind to (default localhost only).
    """
    app = create_app()
    url = f"http://{host}:{port}"

    # Open browser after a short delay
    if open_browser:
        def open_browser_delayed():
            import time
            time.sleep(0.5)
            webbrowser.open(url)

        threading.Thread(target=open_browser_delayed, daemon=True).start()

    print(f"\n⚙️  Clanker Config running at {url}")
    print("   Press Ctrl+C to stop\n")

    # Run server
    config = uvicorn.Config(
        app,
        host=host,
        port=port,
        log_level="warning",
        access_log=False,
    )
    server = uvicorn.Server(config)

    try:
        server.run()
    except KeyboardInterrupt:
        print("\n\n✓ Config server stopped")
