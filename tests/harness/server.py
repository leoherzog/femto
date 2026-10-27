"""Static HTTP server for the repository root on 127.0.0.1 and a free port.

Text types carry charset=utf-8, so reference chunks without @charset decode the same way as the
monolithic file. Every 404 is recorded; the runner turns them into harness errors.
"""
import http.server
import threading
from functools import partial

from .paths import REPO


class _Handler(http.server.SimpleHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    extensions_map = {
        **http.server.SimpleHTTPRequestHandler.extensions_map,
        ".css": "text/css; charset=utf-8",
        ".js": "text/javascript; charset=utf-8",
        ".mjs": "text/javascript; charset=utf-8",
        ".html": "text/html; charset=utf-8",
        ".json": "application/json; charset=utf-8",
        ".svg": "image/svg+xml",
        ".txt": "text/plain; charset=utf-8",
    }

    def __init__(self, *args, server_state=None, **kwargs):
        self.server_state = server_state
        super().__init__(*args, **kwargs)

    def end_headers(self):
        self.send_header("Cache-Control", "no-cache")
        super().end_headers()

    def send_error(self, code, message=None, explain=None):
        if code == 404 and self.server_state is not None:
            with self.server_state["lock"]:
                self.server_state["missing"].append(self.path)
        super().send_error(code, message, explain)

    def log_message(self, *args):
        pass


class Server:
    def __init__(self, root=REPO):
        self.state = {"missing": [], "lock": threading.Lock()}
        handler = partial(_Handler, directory=str(root), server_state=self.state)
        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.httpd.daemon_threads = True
        self.base = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True, name="http")
        self.thread.start()

    def take_missing(self):
        with self.state["lock"]:
            out, self.state["missing"] = self.state["missing"], []
        return out

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()
