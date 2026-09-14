"""Portable server: serve the built UI and API from the configured port."""
import argparse
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import socket
import threading
import time
import urllib.request
import webbrowser

ROOT = Path(__file__).resolve().parent


def create_portable_app():
    from backend.main import app
    from fastapi import HTTPException
    from fastapi.responses import FileResponse
    from fastapi.staticfiles import StaticFiles

    dist = ROOT / 'frontend' / 'dist'
    if not (dist / 'index.html').is_file():
        raise RuntimeError('Missing frontend/dist/index.html')
    app.mount('/assets', StaticFiles(directory=dist / 'assets'), name='assets')

    @app.get('/{path:path}', include_in_schema=False)
    async def frontend(path: str):
        if path == 'api' or path.startswith(('api/', 'ws/', 'assets/')):
            raise HTTPException(404)
        candidate = (dist / path).resolve()
        if not candidate.is_relative_to(dist.resolve()):
            raise HTTPException(404)
        if candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(dist / 'index.html')

    return app


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--no-browser', action='store_true')
    args = parser.parse_args()
    os.chdir(ROOT)
    (ROOT / 'logs').mkdir(exist_ok=True)
    from backend.config import get_config
    config = get_config()
    # Reserve the listening socket before opening the browser or initializing DB.
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    if os.name == 'nt':
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
    listener.bind((config.server.host, config.server.port))
    listener.listen(128)
    app = create_portable_app()
    handler = RotatingFileHandler(ROOT / 'logs' / 'platform.log', maxBytes=5_000_000,
                                  backupCount=3, encoding='utf-8')
    handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(name)s %(message)s'))
    logging.getLogger().addHandler(handler)
    url = f'http://127.0.0.1:{config.server.port}'
    if not args.no_browser:
        def open_when_ready():
            for _ in range(120):
                try:
                    with urllib.request.urlopen(url + '/readyz', timeout=1) as response:
                        if response.status == 200:
                            webbrowser.open(url)
                            return
                except Exception:
                    time.sleep(0.5)
        threading.Thread(target=open_when_ready, daemon=True).start()
    print(f'Observation Platform: {url}\nPress Ctrl+C to stop.', flush=True)
    import uvicorn
    server = uvicorn.Server(uvicorn.Config(app, log_level='info', workers=1))
    try:
        server.run(sockets=[listener])
    finally:
        listener.close()


if __name__ == '__main__':
    main()
