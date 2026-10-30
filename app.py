import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "scripts"))
from weather_join import CACHE, build_payload

DATA = ROOT / "data"
INDEX = ROOT / "index.html"
BASELINES = ROOT / "baselines.html"
PORT = 8000

STATIC = {
    "/data/weather_power.json": (
        DATA / "weather_power.json",
        "application/json; charset=utf-8",
    ),
    "/data/weather_power.csv": (DATA / "weather_power.csv", "text/csv; charset=utf-8"),
    "/data/weather_power_3days.csv": (
        DATA / "weather_power_3days.csv",
        "text/csv; charset=utf-8",
    ),
    "/data/hourly.csv": (DATA / "hourly.csv", "text/csv; charset=utf-8"),
    "/data/monthly_daily.csv": (
        DATA / "monthly_daily.csv",
        "text/csv; charset=utf-8",
    ),
    "/data/baselines_summary.json": (
        DATA / "baselines_summary.json",
        "application/json; charset=utf-8",
    ),
    "/data/baselines_summary.csv": (
        DATA / "baselines_summary.csv",
        "text/csv; charset=utf-8",
    ),
    "/data/baselines_daily.csv": (
        DATA / "baselines_daily.csv",
        "text/csv; charset=utf-8",
    ),
    "/data/baselines_hourly.csv": (
        DATA / "baselines_hourly.csv",
        "text/csv; charset=utf-8",
    ),
}

PAYLOAD = None


def get_payload():
    global PAYLOAD
    if PAYLOAD is None:
        PAYLOAD = build_payload()
    return PAYLOAD


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        path = urlparse(self.path).path
        if path in ("/", "/index.html"):
            self.serve_file(INDEX, "text/html; charset=utf-8")
        elif path == "/baselines.html":
            self.serve_file(BASELINES, "text/html; charset=utf-8")
        elif path == "/api/weather":
            self.serve_api()
        elif path in STATIC:
            file_path, content_type = STATIC[path]
            self.serve_file(file_path, content_type)
        else:
            self.send_text(404, "not found")

    def serve_api(self):
        try:
            payload = get_payload()
        except Exception as error:
            self.send_text(502, f"Open-Meteo API error: {error}")
            return
        self.send_json(payload)

    def serve_file(self, path, content_type):
        try:
            body = path.read_bytes()
        except OSError as error:
            self.send_text(500, f"{path.name}: {error}")
            return
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def send_json(self, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def send_text(self, code, text):
        body = text.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        print(f"{self.address_string()} {fmt % args}")


def main():
    global PAYLOAD
    if "--refresh" in sys.argv and CACHE.exists():
        CACHE.unlink()
        PAYLOAD = None
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print(f"serving on port {PORT}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
