"""Authenticated loopback read-only service. No raw paths/logs in responses."""
import hmac
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit
from .aggregate import aggregate
from .timeutil import utcnow


class CollectorService:
    def __init__(self, index, prices, config, compatibility=None):
        self.index, self.prices, self.config = index, prices, config
        self.compatibility = compatibility
        self.stop = threading.Event()
        self.wake = threading.Event()
        self.output_lock = threading.Lock()
        self.failure = None
        self.last_refresh = 0

    def refresh(self):
        # Repeated clients coalesce into the same Event and the single worker.
        self.wake.set()

    def worker(self):
        while not self.stop.is_set():
            try:
                self.index.scan()
                self.failure = None
                self.last_refresh = time.monotonic()
            except Exception:
                # Do not put filesystem errors, raw lines or exception bodies in API output.
                self.failure = "scan_failed"
            self.wake.wait(0.25 if self.index.indexing else 5)
            self.wake.clear()
            if time.monotonic() - self.last_refresh < 0.25:
                self.stop.wait(0.25)

    def today(self, options):
        self.refresh()
        with self.output_lock:
            self.prices.reload()
            self.index.price_version(self.prices.table["priceVersion"] if self.prices.table else None)
            result = aggregate(self.index, self.prices, self.config["timezone"], **options)
            if self.failure:
                result["dataStatus"], result["totalCostUSD"] = "partial", None
                result["diagnostics"].append({"code": "scan_failed", "count": 1, "message": "索引任务失败，显示上次结果"})
            if self.compatibility:
                self.compatibility.enrich(result["compatibility"])
            return result

    def handler(self):
        service = self

        class Handler(BaseHTTPRequestHandler):
            server_version = "CodexUsage/1"
            sys_version = ""

            def log_message(self, *_):
                pass

            def _write(self, status, body=None, origin=None):
                encoded = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode() if body is not None else b""
                self.send_response(status)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(encoded)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                if origin:
                    self.send_header("Access-Control-Allow-Origin", origin)
                    self.send_header("Vary", "Origin")
                    self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
                    self.send_header("Access-Control-Allow-Headers", "Authorization")
                    self.send_header("Access-Control-Max-Age", "300")
                try:
                    self.end_headers()
                    if encoded:
                        self.wfile.write(encoded)
                except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                    pass

            def _origin(self):
                hosts = self.headers.get_all("Host", [])
                if len(hosts) != 1 or hosts[0] != f"127.0.0.1:{self.server.server_port}":
                    return False, None
                origins = self.headers.get_all("Origin", [])
                if len(origins) > 1:
                    return False, None
                origin = origins[0] if origins else None
                if origin and origin not in service.config["allowedOrigins"]:
                    return False, None
                # No Origin is accepted only for an authenticated local CLI/bridge.
                return True, origin

            def do_OPTIONS(self):
                ok, origin = self._origin()
                if not ok or not origin or self.headers.get("Access-Control-Request-Method") != "GET" or self.headers.get("Access-Control-Request-Headers", "").lower() not in ("", "authorization"):
                    return self._write(403, {"error": "forbidden"})
                self._write(204, origin=origin)

            def do_GET(self):
                ok, origin = self._origin()
                auths = self.headers.get_all("Authorization", [])
                expected = "Bearer " + service.config["pairingToken"]
                if not ok or len(auths) != 1 or not hmac.compare_digest(auths[0].encode(), expected.encode()):
                    return self._write(403, {"error": "forbidden"})
                parsed = urlsplit(self.path)
                if parsed.path == "/v1/health" and not parsed.query:
                    return self._write(200, {"schemaVersion": "1", "status": "degraded" if service.failure else "ok",
                        "indexStatus": "unavailable" if service.index.unavailable else "indexing" if service.index.indexing else "ready",
                        "lastSuccessfulScanAt": service.index.last_scan, "generatedAt": utcnow()}, origin)
                if parsed.path != "/v1/today":
                    return self._write(404, {"error": "not_found"}, origin)
                query = parse_qs(parsed.query, keep_blank_values=True)
                if set(query) - {"includeInternal", "includeCLI", "includeOther"} or any(len(v) != 1 or v[0] not in ("true", "false") for v in query.values()):
                    return self._write(400, {"error": "invalid_options"}, origin)
                options = {k: query.get(q, ["false"])[0] == "true" for k, q in (("include_internal", "includeInternal"), ("include_cli", "includeCLI"), ("include_other", "includeOther"))}
                try:
                    self._write(200, service.today(options), origin)
                except Exception:
                    self._write(503, {"error": "summary_unavailable"}, origin)

            def do_POST(self):
                self._write(405, {"error": "read_only"})

        return Handler

    def serve(self, stop_file=None, ready_file=None):
        # Binding provides a global single-instance guard for this configured port.
        server = ThreadingHTTPServer(("127.0.0.1", self.config["port"]), self.handler())
        server.daemon_threads = True
        server.timeout = 0.5
        worker = threading.Thread(target=self.worker, name="usage-index", daemon=True)
        worker.start()
        if ready_file:
            ready_file.write_text(json.dumps({"pid": __import__("os").getpid(), "port": server.server_port}), encoding="utf-8")
        try:
            while not self.stop.is_set():
                if stop_file and stop_file.exists():
                    stop_file.unlink()
                    break
                server.handle_request()
        finally:
            self.stop.set()
            self.wake.set()
            worker.join()
            server.server_close()
            if ready_file:
                ready_file.unlink(missing_ok=True)
