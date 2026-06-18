"""`railway_api_discover` — find Tripideas's Postgres DATABASE_URL via Railway API.

Phase 0.5 of the bucket-integration discovery: the user gave us a Railway
API token + project ID (not a direct DATABASE_URL). This script uses
Railway's GraphQL API to walk the project → environments → services and
surface the Postgres connection string so the existing schema probe
(railway_schema_probe.py) can then connect.

READ-ONLY: only GraphQL `query` operations are issued, never `mutation`.
The token must never be used to write — this is a hard constraint from
the user. Every call site in this file is a query, and there is no
mutation helper defined.

Setup (already done):
    .env contains RAILWAY_API_TOKEN and RAILWAY_PROJECT_ID

Run:
    python execution/audit/railway_api_discover.py

Output:
    - Project name + environments + services
    - For each Postgres-like service, prints the relevant connection vars
    - Writes the staging DATABASE_URL into .env as RAILWAY_DATABASE_URL
      so railway_schema_probe.py can pick it up next.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

import requests

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

try:
    from dotenv import load_dotenv
    load_dotenv(_PROJECT_ROOT / ".env")
except ImportError:
    print("ERROR: python-dotenv not installed (should be — check backend/requirements.txt)")
    sys.exit(1)


RAILWAY_GQL_URL = "https://backboard.railway.app/graphql/v2"

# DB connection-string variable names commonly used by Railway plugins
DB_URL_KEYS = (
    "DATABASE_URL",
    "DATABASE_PUBLIC_URL",     # Railway Postgres plugin sets this for external access
    "POSTGRES_URL",
    "PG_URL",
)


def gql(query: str, variables: dict | None = None) -> dict:
    """Issue a Railway GraphQL query. NEVER a mutation.

    Railway has two token flavours that use different headers:
    - Account/team API tokens: Authorization: Bearer <token>
    - Project-scoped tokens (from Project Settings -> Tokens): Project-Access-Token: <token>

    We try project-token first since the user said "Staging Railway API token"
    (project-scoped naming). Fall back to Bearer if that fails with "Not
    Authorized".
    """
    token = os.environ["RAILWAY_API_TOKEN"]
    base_headers = {"Content-Type": "application/json"}

    last_error: str | None = None
    for header_variant in (
        {"Project-Access-Token": token},
        {"Authorization": f"Bearer {token}"},
    ):
        headers = {**base_headers, **header_variant}
        r = requests.post(
            RAILWAY_GQL_URL,
            headers=headers,
            json={"query": query, "variables": variables or {}},
            timeout=30,
        )
        if r.status_code != 200:
            last_error = f"HTTP {r.status_code}: {r.text[:300]}"
            continue
        body = r.json()
        if "errors" in body and body["errors"]:
            msgs = [e.get("message", "") for e in body["errors"]]
            if any("Not Authorized" in m or "Unauthorized" in m for m in msgs):
                last_error = json.dumps(body["errors"], indent=2)
                continue
            raise RuntimeError(f"Railway GraphQL errors: {last_error or json.dumps(body['errors'], indent=2)}")
        return body["data"]
    raise RuntimeError(f"Railway GraphQL auth failed under both header variants. Last error:\n{last_error}")


def discover() -> None:
    project_id = os.environ["RAILWAY_PROJECT_ID"]
    token = os.environ.get("RAILWAY_API_TOKEN")
    if not token:
        print("ERROR: RAILWAY_API_TOKEN missing from .env")
        sys.exit(1)

    print(f"Querying Railway project {project_id}...")

    # ---- Project + environments + services (top-level shape) ----
    project = gql(
        """
        query ($id: String!) {
          project(id: $id) {
            id
            name
            environments {
              edges { node { id name } }
            }
            services {
              edges { node { id name } }
            }
          }
        }
        """,
        {"id": project_id},
    )["project"]

    print(f"  project.name: {project['name']}")
    envs = [e["node"] for e in project["environments"]["edges"]]
    services = [s["node"] for s in project["services"]["edges"]]
    print(f"  environments ({len(envs)}): " + ", ".join(f"{e['name']}({e['id'][:8]})" for e in envs))
    print(f"  services ({len(services)}):     " + ", ".join(f"{s['name']}({s['id'][:8]})" for s in services))
    print()

    # ---- For each (env, service) combo, pull variables ----
    discovered_db_urls: list[tuple[str, str, str, str]] = []  # (env, service, key, url)
    for env in envs:
        for svc in services:
            try:
                vars_data = gql(
                    """
                    query ($projectId: String!, $environmentId: String!, $serviceId: String!) {
                      variables(
                        projectId: $projectId,
                        environmentId: $environmentId,
                        serviceId: $serviceId
                      )
                    }
                    """,
                    {
                        "projectId": project_id,
                        "environmentId": env["id"],
                        "serviceId": svc["id"],
                    },
                )
            except Exception as e:
                print(f"  ! could not read vars for env={env['name']} svc={svc['name']}: {e}")
                continue

            vars_map: dict[str, str] = vars_data.get("variables") or {}
            if not vars_map:
                continue

            db_keys_found = [k for k in vars_map.keys() if any(needle in k for needle in DB_URL_KEYS)]
            if db_keys_found:
                print(f"  env={env['name']:12s} svc={svc['name']:24s} → DB-ish keys: {db_keys_found}")
                for k in db_keys_found:
                    v = vars_map[k]
                    masked = _mask_connection_string(v)
                    print(f"      {k} = {masked}")
                    discovered_db_urls.append((env["name"], svc["name"], k, v))

    if not discovered_db_urls:
        print("\nNo DATABASE_URL-style variables found across any (env, service).")
        print("Possible causes:")
        print("  - The Postgres plugin isn't attached to this project (unlikely if the site works)")
        print("  - The token is scoped to a different project (double-check RAILWAY_PROJECT_ID)")
        print("  - Railway changed their var-naming convention")
        sys.exit(2)

    # ---- Pick staging Postgres URL and stash in .env ----
    # Heuristic: prefer service name containing 'postgres'/'db', env named 'staging'
    def score(t: tuple[str, str, str, str]) -> int:
        env, svc, key, url = t
        s = 0
        if "postgres" in svc.lower() or "db" in svc.lower(): s += 10
        if env.lower() == "staging": s += 5
        if key == "DATABASE_PUBLIC_URL": s += 3   # external-access URL is what we need from outside Railway
        elif key == "DATABASE_URL": s += 2
        return s

    discovered_db_urls.sort(key=score, reverse=True)
    best = discovered_db_urls[0]
    env_n, svc_n, key_n, url_n = best
    print(f"\nPicked: env={env_n} svc={svc_n} key={key_n}")
    print(f"  ({_mask_connection_string(url_n)})")

    _stash_in_env_file("RAILWAY_DATABASE_URL", url_n)
    print(f"\nWrote RAILWAY_DATABASE_URL to .env. Next step:")
    print(f"  python execution/audit/railway_schema_probe.py")


def _mask_connection_string(url: str) -> str:
    """Mask password in a postgres://user:pass@host/db URL for safe display."""
    # Crude but effective: replace anything between : and @ in the credentials portion
    if "://" not in url:
        return url
    scheme, rest = url.split("://", 1)
    if "@" not in rest:
        return url
    creds, hostpart = rest.rsplit("@", 1)
    if ":" in creds:
        user, _pw = creds.split(":", 1)
        creds = f"{user}:****"
    return f"{scheme}://{creds}@{hostpart}"


def _stash_in_env_file(key: str, value: str) -> None:
    """Append or replace a `key=value` line in the project .env file."""
    env_path = _PROJECT_ROOT / ".env"
    lines: list[str] = []
    if env_path.exists():
        lines = env_path.read_text(encoding="utf-8").splitlines()
    replaced = False
    for i, line in enumerate(lines):
        if line.startswith(f"{key}="):
            lines[i] = f"{key}={value}"
            replaced = True
            break
    if not replaced:
        if lines and lines[-1].strip():
            lines.append("")
        lines.append(f"# Auto-set by railway_api_discover.py (staging Postgres)")
        lines.append(f"{key}={value}")
    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except (AttributeError, OSError):
            pass
    discover()
