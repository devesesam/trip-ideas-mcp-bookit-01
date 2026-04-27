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

# --- Secret: ANTHROPIC_API_KEY + SANITY_* live here ---
# User creates this once via:
#   modal secret create tripideas-secrets ANTHROPIC_API_KEY=sk-ant-... \
#     SANITY_PROJECT_ID=n1o990un SANITY_DATASET=production \
#     SANITY_API_VERSION=v2025-02-19 SANITY_TOKEN=...
secret = modal.Secret.from_name("tripideas-secrets")

app = modal.App("tripideas-chat", image=image, secrets=[secret])


@app.function(
    image=image,
    secrets=[secret],
    min_containers=0,                 # scale to zero when idle
    max_containers=5,                 # cap at 5 concurrent containers (tune later)
    timeout=120,                      # per-request timeout
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
