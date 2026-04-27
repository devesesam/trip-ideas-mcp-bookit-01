# Tripideas Chat

Conversational trip-planning assistant for [tripideas.nz](https://tripideas.nz). Turns vague travel intent ("3-day Northland coastal trip with my partner") into concrete, refinable itineraries grounded in Tripideas's editorial Sanity content.

## Architecture

```
Tripideas.nz visitor
  ↓ <script> embed
Frontend chat widget (Vite + React + @ai-sdk/react)
  hosted on Netlify, auto-deploy from GitHub
  ↓ HTTPS POST /chat (SSE streaming)
Backend orchestrator (FastAPI + Anthropic SDK + 5 tools)
  hosted on Modal as @modal.asgi_app
  ↓ GROQ
Sanity (production dataset)
```

Five planning tools, all deterministic Python:

| Tool | Purpose |
|---|---|
| `search_places` | Find places in a NZ region matching optional filters |
| `get_place_summary` | Full detail on one place |
| `build_day_itinerary` | One-day plan from a base location + filters |
| `build_trip_itinerary` | Multi-day chain with cross-day variety |
| `refine_itinerary` | Adjust an existing day plan |

## Repo layout

```
.
├── execution/        # Python tools — usable from CLI or imported by backend
│   ├── aimetadata/   # parser for the JSON-encoded aiMetadata field
│   ├── tools/        # the 5 planning tools
│   ├── registry/     # NZ regions/subRegions + settlement coord lookup
│   └── ...
├── backend/          # FastAPI + Anthropic orchestrator, Modal deploy
├── frontend/         # React chat widget, Netlify deploy (Sprint 4)
├── directives/       # SOPs, audits, source brief
└── .tmp/             # local-only intermediates (gitignored)
```

## Setup (local development)

```bash
# 1. Install Python deps
pip install -r backend/requirements.txt

# 2. Copy .env.example → .env and fill in:
#    - SANITY_TOKEN
#    - ANTHROPIC_API_KEY (https://console.anthropic.com/settings/keys)

# 3. Test a tool against live Sanity (no LLM call)
python execution/tools/search_places.py

# 4. Test the orchestrator in your terminal (uses LLM + Sanity)
python backend/cli_chat.py
```

### Run backend + frontend locally (full chat in browser)

```bash
# Terminal 1 — backend
cd backend
uvicorn orchestrator:create_app --factory --reload --port 8000

# Terminal 2 — frontend
cd frontend
npm install        # one-off
npm run dev        # serves at http://localhost:5173
```

Open http://localhost:5173 and click **Plan a trip** in the bottom-right.

## Deploying

### Backend → Modal

```bash
# One-off: install Modal CLI + auth
pip install modal
modal token new

# One-off: register the secrets bundle
modal secret create tripideas-secrets \
  ANTHROPIC_API_KEY=sk-ant-... \
  SANITY_PROJECT_ID=n1o990un \
  SANITY_DATASET=production \
  SANITY_API_VERSION=v2025-02-19 \
  SANITY_TOKEN=...

# Deploy (and re-deploy on every backend change)
modal deploy backend/modal_app.py
# Modal prints a public URL like https://<workspace>--tripideas-chat-web.modal.run
```

### Frontend → Netlify

`netlify.toml` at the repo root tells Netlify to build from `frontend/`. Push to GitHub and Netlify auto-deploys.

After the first deploy, configure the production API URL:
- **Netlify dashboard** → Site → Environment variables → add `VITE_API_URL` = your Modal `/chat` URL
- Re-deploy (or it'll apply on the next git push)

For embedding on Tripideas.nz once both are live:
```html
<div id="tripideas-chat"></div>
<script
  src="https://<netlify-site>/assets/index-XXX.js"
  data-api-url="https://<modal-app>--web.modal.run/chat"
></script>
<link rel="stylesheet" href="https://<netlify-site>/assets/index-XXX.css">
```

(For a clean single-file embed, we can switch Vite to library mode in a later iteration — Sprint 4 ships SPA-mode as v1.)

## Testing prompts

The orchestrator should handle these end-to-end:

- *"Give me a 3-day Northland getaway idea"*
- *"Plan a relaxed South Island itinerary for 7 days"*
- *"What can we do near Queenstown with kids?"*
- *"Swap day two for something cheaper and easier"*
- *"Make this itinerary more relaxed and remove long drives"*
- *"4-day road trip from Nelson to Christchurch"*

## Background

- Build plan: `~/.claude/plans/hey-this-is-a-wobbly-squirrel.md`
- Source brief from Douglas: `directives/tripideas_mcp_brief.md`
- Live corpus audit (2026-04-27): `directives/corpus_audit_2026-04-27.md`
- Tag vocabulary: `directives/tag_vocabulary.md`
