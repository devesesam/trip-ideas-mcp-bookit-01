# Deployment — Modal + Netlify

**Source of truth for where this project is hosted.** Read this before running any `modal deploy` or touching infrastructure.

---

## Modal (backend)

| Field | Value |
|---|---|
| **Workspace / profile** | `devesesam` |
| **App name** | `tripideas-chat` |
| **Environment** | `main` (default) |
| **Entry point** | [`backend/modal_app.py`](../backend/modal_app.py) |
| **Public URL** | Printed by `modal deploy`; also visible at https://modal.com/apps/devesesam/main/tripideas-chat |

### Secrets attached to the app

Both must exist in the **`devesesam`** workspace before `modal deploy` will succeed.

| Secret name | Keys | Used by |
|---|---|---|
| `tripideas-secrets` | `ANTHROPIC_API_KEY`, `SANITY_PROJECT_ID`, `SANITY_DATASET`, `SANITY_API_VERSION`, `SANITY_TOKEN` | Orchestrator (Anthropic SDK), all tools that hit Sanity |
| `google-maps-secret` | `GOOGLE_MAPS_API_KEY` | [`execution/services/google_maps.py`](../execution/services/google_maps.py) — drive times + polylines for `build_day_itinerary` and `build_trip_itinerary` |

Manage at https://modal.com/secrets/devesesam/main.

### Deploy commands

```bash
# Confirm the active profile is devesesam (NOT rvnu or any other workspace)
modal profile current   # must print: devesesam

# If it's anything else:
modal profile activate devesesam

# Deploy. The PYTHONIOENCODING/PYTHONUTF8 prefix is required on Windows
# because Modal's CLI prints Unicode that crashes the cp1252 console.
PYTHONIOENCODING=utf-8 PYTHONUTF8=1 modal deploy backend/modal_app.py
```

### Anthropic Console settings (org-admin requirement)

Beyond the Modal secrets above, **Web Search must be enabled in the Anthropic Console** for the API key referenced by `tripideas-secrets`. Toggle is at https://console.anthropic.com/settings/privacy (org admin only). Currently enabled for the workspace owning `ANTHROPIC_API_KEY`. If `web_search` ever returns `unavailable` or `invalid_input` error blocks unexpectedly, this is the first thing to check.

### Common gotchas

- **Wrong workspace.** `modal profile list` shows multiple profiles for this user (`devesesam`, `rvnu`). Only `devesesam` has `tripideas-secrets` and `google-maps-secret`. Deploying from another profile fails with `Secret '...' not found in environment 'main'`.
- **Modal token pairs.** Tokens are `(ak-..., as-...)` pairs stored in `~/.modal.toml`. Generated via the browser-OAuth flow `modal token new` — preferred over manual token-pair handling.
- **Console encoding crash on Windows.** Modal's CLI emits Unicode glyphs that crash cp1252 (the default Windows console encoding). Always prefix with `PYTHONIOENCODING=utf-8 PYTHONUTF8=1`.
- **Warm containers serve stale code after redeploy.** With `min_containers=0` and a warm container still alive, `modal deploy` succeeds but new requests sometimes keep hitting the old container with the old in-memory code. The `/` health response will show the *previous* `prompt_version` even though the deploy log says success. Workaround when you need to verify a code change immediately: `modal app stop <app_id>` (find it via `modal app list`) then redeploy. The cold restart picks up the new code on the next request.
- **Adding a new secret to the app.** Two-step:
  1. Create the secret. Either via the Modal web UI (https://modal.com/secrets/devesesam/main — keeps values out of shell history) or via CLI: `modal secret create <name> KEY=value`.
  2. Reference it by name in `backend/modal_app.py`'s `SECRETS` list. Re-deploy.

---

## Netlify (frontend)

| Field | Value |
|---|---|
| **Build base** | `frontend/` |
| **Build command** | `npm install && npm run build` |
| **Publish dir** | `dist/` (relative to base — i.e. `frontend/dist/`) |
| **Config file** | [`netlify.toml`](../netlify.toml) at repo root |
| **Auto-deploy** | On every push to `main` |

The frontend talks to the Modal backend via `data-api-url` on the embed `<div>`. Update that attribute when the Modal URL changes.

---

## When this file goes stale

- Modal workspace changes → update the **Workspace / profile** row.
- A new secret is added → add a row to the secrets table AND update `backend/modal_app.py`.
- A new deployment target is added (e.g., a worker, a cron) → new section here.
