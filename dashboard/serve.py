"""Minimal static file server for the LENS dashboard on port 8800."""
import http.server
import socketserver
from pathlib import Path

PORT = 8800
DIR = Path(__file__).parent / "ui"


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(DIR), **kwargs)

    def log_message(self, format, *args):
        pass  # suppress access logs


if __name__ == "__main__":
    with socketserver.TCPServer(("", PORT), Handler) as httpd:
        print(f"[LENS] Dashboard at http://localhost:{PORT}")
        httpd.serve_forever()
