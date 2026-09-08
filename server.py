import sys
import json
import os
from http.server import SimpleHTTPRequestHandler, HTTPServer

PORT = int(os.environ.get("PORT", 3456))
DIRECTORY = os.path.dirname(os.path.abspath(__file__))


def get_config_path() -> str:
    env_path = os.environ.get("CONFIG_PATH")
    if env_path:
        return env_path
    data_dir = os.path.join(DIRECTORY, "data")
    if os.path.exists(data_dir):
        return os.path.join(data_dir, "config.json")
    return os.path.join(DIRECTORY, "config.json")


class CustomHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=DIRECTORY, **kwargs)

    def do_GET(self):
        # Serve config.json directly from active location if requested
        if self.path.startswith("/config.json"):
            config_path = get_config_path()
            if os.path.exists(config_path):
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                with open(config_path, "rb") as f:
                    self.wfile.write(f.read())
                return
        super().do_GET()

    def do_POST(self):
        if self.path == "/api/save-config":
            try:
                content_length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(content_length).decode("utf-8")
                payload = json.loads(body)

                config_path = get_config_path()
                os.makedirs(os.path.dirname(config_path), exist_ok=True)

                # Read existing config to preserve internal fields (e.g. device_id)
                existing = {}
                if os.path.exists(config_path):
                    try:
                        with open(config_path, "r", encoding="utf-8") as f:
                            existing = json.load(f)
                    except Exception:
                        existing = {}

                # Merge: only update fields that the frontend manages
                if "schedules" in payload:
                    existing["schedules"] = payload["schedules"]
                if "credentials" in payload:
                    existing["credentials"] = payload["credentials"]

                with open(config_path, "w", encoding="utf-8") as f:
                    json.dump(existing, f, indent=2, ensure_ascii=False)

                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(json.dumps({"success": True, "message": "Saved successfully"}).encode("utf-8"))
            except Exception as e:
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(json.dumps({"success": False, "error": str(e)}).encode("utf-8"))
        else:
            self.send_response(404)
            self.end_headers()

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()


def run():
    server_address = ("", PORT)
    httpd = HTTPServer(server_address, CustomHandler)
    print(f"RU Bot Server rodando em: http://localhost:{PORT}")
    print("Pressione Ctrl+C para encerrar.")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nServidor finalizado.")
        httpd.server_close()


if __name__ == "__main__":
    run()
