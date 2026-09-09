"""Central configuration — all env vars and paths in one place."""

import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()  # loads .env from the project root if present

# ── Paths ────────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent
STATE_FILE = BASE_DIR / "webinar_state.json"
REFERENCES_DIR = BASE_DIR / "references"
ONEDRIVE_BASE = Path.home() / "OneDrive - Pharma D-mand"
CLIENTS_PATH = ONEDRIVE_BASE / "Marketing" / "Clients"

# Confirmed OneDrive structure:
# ~/OneDrive - Pharma D-mand/Marketing/Clients/{Client}/
# Reference examples live in:
# ~/OneDrive - Pharma D-mand/Marketing/Cam's work/Work/PD-Create/Examples/

# ── Agent webhook server ──────────────────────────────────────────────────────
AGENT_HOST = os.environ.get("AGENT_HOST", "localhost")
AGENT_PORT = int(os.environ.get("AGENT_PORT", "8765"))
AGENT_CALLBACK_URL = os.environ.get(
    "AGENT_CALLBACK_URL", f"http://localhost:{AGENT_PORT}"
)

# ── Hub ───────────────────────────────────────────────────────────────────────
HUB_URL = os.environ.get("HUB_URL", "http://localhost:3000")
HUB_SECRET = os.environ.get("HUB_SECRET", "")

# ── Email ─────────────────────────────────────────────────────────────────────
NOTIFY_RECIPIENTS = ["cameron@pharmad-mand.com"]
EMAIL_SENDER = os.environ.get("EMAIL_SENDER", "")
SMTP_HOST = os.environ.get("SMTP_HOST", "")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_PASS = os.environ.get("SMTP_PASS", "")

# ── Anthropic ─────────────────────────────────────────────────────────────────
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

# ── Monitor ───────────────────────────────────────────────────────────────────
# How often the monitor polls the webinars page (seconds). Default: 1 hour.
POLL_INTERVAL = int(os.environ.get("POLL_INTERVAL", str(60 * 60)))

# How long to wait for a human approval before timing out (seconds). Default: 24 h.
APPROVAL_TIMEOUT = int(os.environ.get("APPROVAL_TIMEOUT", str(24 * 60 * 60)))
