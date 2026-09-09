"""
Lightweight HTTP server that receives hub relay callbacks on POST /webhook/hub.

Two gate types are routed via the payload's "type" field:
  - "webinar_detection" (Gate 1): scrape approval from the Webinars page
  - anything else / no type   (Gate 2): campaign draft approval from Campaigns page

Uses threading.Event to signal the main workflow thread.
"""

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer


class ApprovalBus:
    """Thread-safe signal bus between the webhook server and the orchestrator."""

    def __init__(self):
        self._gate1_event = threading.Event()
        self._gate1_decision: str | None = None
        self._hub_event = threading.Event()
        self._hub_decision: str | None = None
        self._hub_payload: dict = {}
        self._lock = threading.Lock()

    # ── Gate 1 (webinar detection) ────────────────────────────────────────────

    def arm_gate1(self) -> None:
        """Clear the gate ready for a new detection callback."""
        self._gate1_event.clear()
        with self._lock:
            self._gate1_decision = None

    def wait_gate1(self, timeout: float | None = None) -> str | None:
        """Block until Gate 1 is resolved. Returns 'approve', 'reject', or None (timeout)."""
        self._gate1_event.wait(timeout=timeout)
        return self._gate1_decision

    def handle_gate1(self, decision: str) -> None:
        """Called by the webhook handler with the hub's Gate 1 decision."""
        with self._lock:
            self._gate1_decision = decision
        self._gate1_event.set()

    # ── Gate 2 (campaign drafts) ──────────────────────────────────────────────

    def arm_hub(self) -> None:
        """Clear the hub gate ready for a new callback."""
        self._hub_event.clear()
        with self._lock:
            self._hub_decision = None
            self._hub_payload = {}

    def wait_hub(self, timeout: float | None = None) -> tuple[str | None, dict]:
        """Block until the hub calls back. Returns (decision, payload)."""
        self._hub_event.wait(timeout=timeout)
        return self._hub_decision, self._hub_payload

    def handle_hub(self, decision: str, payload: dict) -> None:
        """Called by the webhook handler with the hub's Gate 2 decision."""
        with self._lock:
            self._hub_decision = decision
            self._hub_payload = payload
        self._hub_event.set()


# ── HTTP handler ──────────────────────────────────────────────────────────────

class _Handler(BaseHTTPRequestHandler):
    bus: ApprovalBus = None  # injected by WebhookServer

    def do_POST(self):
        if self.path != "/webhook/hub":
            self._respond(404, {"error": "not found"})
            return

        length = int(self.headers.get("Content-Length", 0))
        body = {}
        if length:
            try:
                body = json.loads(self.rfile.read(length))
            except json.JSONDecodeError:
                self._respond(400, {"error": "invalid JSON"})
                return

        # Hub relay sends event as "approved" / "rejected"
        event = body.get("event", "").lower()
        if event not in ("approved", "rejected"):
            self._respond(400, {"error": "event must be 'approved' or 'rejected'"})
            return

        decision = "approve" if event == "approved" else "reject"
        payload_type = body.get("type", "")

        if payload_type == "webinar_detection":
            self.bus.handle_gate1(decision)
            print(f"[Gate 1] Hub decision: {decision}")
        else:
            self.bus.handle_hub(decision, body)
            print(f"[Gate 2] Hub decision: {decision}")

        self._respond(200, {"status": "received"})

    def _respond(self, code: int, body: dict):
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass  # suppress default access log noise


# ── Server wrapper ────────────────────────────────────────────────────────────

class WebhookServer:
    def __init__(self, host: str, port: int, bus: ApprovalBus):
        self.host = host
        self.port = port
        self.bus = bus
        self._server: HTTPServer | None = None
        self._thread: threading.Thread | None = None

    def start(self):
        _Handler.bus = self.bus
        self._server = HTTPServer((self.host, self.port), _Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        print(f"[Webhook server] Listening on {self.host}:{self.port}")

    def stop(self):
        if self._server:
            self._server.shutdown()


if __name__ == "__main__":
    import config
    bus = ApprovalBus()
    srv = WebhookServer(config.AGENT_HOST, config.AGENT_PORT, bus)
    srv.start()
    print(f"[Webhook server] Running — POST to http://{config.AGENT_HOST}:{config.AGENT_PORT}/webhook/hub")
    print("Ctrl-C to stop")
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        print("\n[Webhook server] Shutting down")
        srv.stop()
