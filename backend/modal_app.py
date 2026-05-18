"""Modal entry point for the Tripideas chat orchestrator.

Deploy:
    modal deploy backend/modal_app.py

That will print a public URL like https://<workspace>--tripideas-chat-web.modal.run
which the frontend points its `/chat` calls at.

Run locally for development (uses your local .env, not Modal secrets):
    cd backend && uvicorn orchestrator:create_app --factory --reload --port 8000
"""

from __future__ import annotations

from pathlib import Path

import modal

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# --- Image: install our requirements + mount the execution/ tools package ---
image = (
    modal.Image.debian_slim(python_version="3.11")
    .pip_install_from_requirements(str(PROJECT_ROOT / "backend" / "requirements.txt"))
    # Make the entire workspace available so backend/* and execution/* import correctly.
    .add_local_dir(str(PROJECT_ROOT / "execution"), remote_path="/root/execution")
    .add_local_dir(str(PROJECT_ROOT / "backend"), remote_path="/root/backend")
)

# --- Secrets ---
# `tripideas-secrets`  — ANTHROPIC_API_KEY + SANITY_*
# `google-maps-secret` — GOOGLE_MAPS_API_KEY (used by execution/services/google_maps.py)
#
# Both created via the Modal CLI / web UI. Listing them on the function
# decorator injects all keys as env vars in the container.
SECRETS = [
    modal.Secret.from_name("tripideas-secrets"),
    modal.Secret.from_name("google-maps-secret"),
]

app = modal.App("tripideas-chat", image=image, secrets=SECRETS)


@app.function(
    image=image,
    secrets=SECRETS,
    min_containers=0,                 # scale to zero when idle
    max_containers=5,                 # cap at 5 concurrent containers (tune later)
    timeout=300,                      # per-request timeout — bumped from 120s
                                      # (2026-05-18) to absorb heavy parallel-tool-call
                                      # bursts (e.g. 17 simultaneous search_places in
                                      # the taxonomy probe). 5 min is a soft cap; chat
                                      # turns should still complete in well under that.
)
@modal.asgi_app()
def web():
    """Modal will serve this ASGI app on a public URL."""
    import sys
    # Ensure /root is importable so `from backend.orchestrator import ...` works
    if "/root" not in sys.path:
        sys.path.insert(0, "/root")
    from backend.orchestrator import create_app
    return create_app()
