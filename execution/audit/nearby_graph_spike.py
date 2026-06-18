"""nearby_graph_spike — read-only audit of the editorial nearby-place graph.

Background
----------
Every `page` doc's `aiMetadata.nearby_places` already holds the editorial
"you might combine this with…" references the article author wrote, parsed
into {name, type, context, distance_text, confidence} by aimetadata.parser.
But that signal is a DEAD END today: it's surfaced only in get_place_summary
and is never used during candidate generation or itinerary greedy-fill, which
fall back to haversine × 1.4 geometry.

Douglas's "Location Association Framework" proposes hand-curating Nearby Groups
across ~1,500 places. Before anyone designs schema or tags the corpus, this
spike answers the prior question with hard numbers: is the editorial graph we
ALREADY have rich, resolvable, and well-clustered enough to bootstrap
recommendations on its own — and where is it thin enough that manual curation
is genuinely needed?

This script is READ-ONLY and uses NO paid LLM/API tokens: one GROQ read of the
corpus, then all name resolution in memory via rapidfuzz (same threshold 80 the
live tools use).

Run:  python execution/audit/nearby_graph_spike.py
Out:  .tmp/nearby_graph_spike.md   (human report)
      .tmp/nearby_graph_edges.json (raw resolved/dangling edges)
"""

from __future__ import annotations

import json
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Optional

_PKG_ROOT = Path(__file__).resolve().parent.parent  # .../execution
if str(_PKG_ROOT) not in sys.path:
    sys.path.insert(0, str(_PKG_ROOT))

from rapidfuzz import fuzz, process  # noqa: E402

from aimetadata.parser import parse  # noqa: E402
from registry.settlements import _haversine_km, _strip_accents  # noqa: E402
from sanity_client import SanityClient  # noqa: E402

_FUZZY_THRESHOLD = 80          # mirrors find_place_by_name / settlements resolver
_CARD_MIN_LINKS = 3            # doc's "minimum 4 places where possible" display rule
_FAR_EDGE_KM = 50.0           # an editorial link this far apart is corridor knowledge geometry can't see
_CLOSE_PAIR_KM = 5.0          # pairs this close that editorial does NOT link → where geometry over-suggests
_GROUP_MAX_KM = 30.0         # cap on edge length when deriving Nearby Groups (stops transcontinental chaining)

_CORPUS_GROQ = (
    '*[_type == "page" && defined(title)]{'
    "_id, title, "
    '"slug": slug.current, '
    "coordinates, "
    "aiMetadata, "
    '"region": subRegion->region->name, '
    '"subRegion": subRegion->name'
    "}"
)


def _coords(doc: dict) -> Optional[tuple[float, float]]:
    c = doc.get("coordinates") or {}
    lat, lng = c.get("lat"), c.get("lng")
    if isinstance(lat, (int, float)) and isinstance(lng, (int, float)):
        return float(lat), float(lng)
    return None


def main() -> None:
    client = SanityClient()
    print("Fetching corpus (one GROQ read)…", file=sys.stderr)
    docs = client.query(_CORPUS_GROQ) or []
    n_total = len(docs)
    print(f"  {n_total} page docs", file=sys.stderr)

    # ---- parse aiMetadata + build name index -------------------------------
    parsed: dict[str, dict] = {}      # _id -> {doc, parsed, nearby, coords, region}
    norm_index: dict[str, list[str]] = defaultdict(list)  # norm title -> [ids] (global)
    norm_titles: list[str] = []       # parallel choice list for rapidfuzz (global)
    norm_title_ids: list[str] = []    # _id per norm_titles entry (global)
    # Region-scoped indexes: most NZ place names that collide (Waipapa, Cathedral
    # Caves, Waitati) sit in different regions, so resolving within the source's
    # region first kills the cross-country fuzzy false positives.
    reg_index: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    reg_titles: dict[str, list[str]] = defaultdict(list)
    reg_title_ids: dict[str, list[str]] = defaultdict(list)

    n_parse_error = 0
    n_with_coords = 0
    for d in docs:
        _id = d["_id"]
        pm = parse(d.get("aiMetadata"))
        if pm.parse_error:
            n_parse_error += 1
        coords = _coords(d)
        if coords:
            n_with_coords += 1
        region = d.get("region")
        parsed[_id] = {"doc": d, "parsed": pm, "nearby": pm.nearby_places,
                       "coords": coords, "region": region}
        nt = _strip_accents(d.get("title") or "")
        if nt:
            norm_index[nt].append(_id)
            norm_titles.append(nt)
            norm_title_ids.append(_id)
            if region:
                reg_index[region][nt].append(_id)
                reg_titles[region].append(nt)
                reg_title_ids[region].append(_id)

    # ---- coverage ----------------------------------------------------------
    link_counts = Counter()           # bucket -> n docs
    n_with_any = 0
    per_doc_link_n: dict[str, int] = {}
    for _id, rec in parsed.items():
        k = len(rec["nearby"])
        per_doc_link_n[_id] = k
        if k:
            n_with_any += 1
        if k == 0:
            link_counts["0"] += 1
        elif k <= 2:
            link_counts["1-2"] += 1
        else:
            link_counts["3+"] += 1
    n_card_ready = sum(1 for v in per_doc_link_n.values() if v >= _CARD_MIN_LINKS)

    # ---- resolvability + edges --------------------------------------------
    # Resolution prefers the source's own region (kills cross-country name
    # collisions), then falls back to a global match flagged "xregion" so we can
    # treat those as lower-confidence. Cache keyed by (needle, region).
    res_cache: dict[tuple[str, Optional[str]], Optional[tuple[str, str, int]]] = {}

    def resolve(name: str, source_id: str, source_region: Optional[str]) -> Optional[tuple[str, str, int]]:
        needle = _strip_accents(name)
        if not needle:
            return None
        key = (needle, source_region)
        if key in res_cache:
            hit = res_cache[key]
        else:
            hit = None
            # 1) in-region exact, 2) in-region fuzzy
            if source_region and source_region in reg_titles:
                ex = reg_index[source_region].get(needle)
                if ex:
                    hit = (ex[0], "exact", 100)
                else:
                    m = process.extractOne(
                        needle, reg_titles[source_region],
                        scorer=fuzz.token_set_ratio, score_cutoff=_FUZZY_THRESHOLD,
                    )
                    if m:
                        hit = (reg_title_ids[source_region][m[2]], "fuzzy", int(m[1]))
            # 3) global fallback, flagged cross-region (suspect for corridor claims)
            if hit is None:
                ex = norm_index.get(needle)
                if ex:
                    hit = (ex[0], "exact_xregion", 100)
                else:
                    m = process.extractOne(
                        needle, norm_titles, scorer=fuzz.token_set_ratio,
                        score_cutoff=_FUZZY_THRESHOLD,
                    )
                    if m:
                        hit = (norm_title_ids[m[2]], "fuzzy_xregion", int(m[1]))
            res_cache[key] = hit
        # Guard against self-match (a place listing itself / its own variant).
        if hit and hit[0] == source_id:
            return None
        return hit

    edges: list[dict] = []            # every editorial nearby reference
    method_counts: Counter = Counter()
    for _id, rec in parsed.items():
        src_title = rec["doc"].get("title") or ""
        src_coords = rec["coords"]
        src_region = rec["region"]
        for np in rec["nearby"]:
            name = (np.name or "").strip()
            if not name:
                continue
            hit = resolve(name, _id, src_region)
            edge = {
                "source_id": _id,
                "source_title": src_title,
                "source_region": src_region,
                "target_name": name,
                "target_id": None,
                "method": "dangling",
                "score": None,
                "confidence": np.confidence,
                "distance_text": np.distance_text,
                "haversine_km": None,
            }
            if hit:
                tgt_id, method, score = hit
                edge["target_id"] = tgt_id
                edge["method"] = method
                edge["score"] = score
                tgt_coords = parsed[tgt_id]["coords"]
                if src_coords and tgt_coords:
                    edge["haversine_km"] = round(
                        _haversine_km(src_coords[0], src_coords[1], tgt_coords[0], tgt_coords[1]), 2
                    )
            method_counts[edge["method"]] += 1
            edges.append(edge)

    n_edges = len(edges)
    n_resolved_exact = method_counts["exact"]
    n_resolved_fuzzy = method_counts["fuzzy"]
    n_xregion = method_counts["exact_xregion"] + method_counts["fuzzy_xregion"]
    n_dangling = method_counts["dangling"]
    n_resolved = n_resolved_exact + n_resolved_fuzzy + n_xregion
    n_inregion = n_resolved_exact + n_resolved_fuzzy

    # ---- graph shape -------------------------------------------------------
    directed: set[tuple[str, str]] = set()
    out_deg: Counter = Counter()
    adj: dict[str, set[str]] = defaultdict(set)  # undirected
    for e in edges:
        if e["target_id"] and e["method"] in ("exact", "fuzzy"):  # in-region only
            s, t = e["source_id"], e["target_id"]
            directed.add((s, t))
            out_deg[s] += 1
            adj[s].add(t)
            adj[t].add(s)
    n_reciprocal = sum(1 for (s, t) in directed if (t, s) in directed)
    reciprocity = (n_reciprocal / len(directed)) if directed else 0.0
    linked_nodes = set(adj.keys())
    avg_out = (len(directed) / len(out_deg)) if out_deg else 0.0

    def components(edge_pairs: set[tuple[str, str]]) -> list[list[str]]:
        """Union-find connected components over an undirected edge set."""
        nodes = {n for pair in edge_pairs for n in pair}
        parent = {n: n for n in nodes}

        def find(x: str) -> str:
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        for a, b in edge_pairs:
            ra, rb = find(a), find(b)
            if ra != rb:
                parent[ra] = rb
        buckets: dict[str, list[str]] = defaultdict(list)
        for n in nodes:
            buckets[find(n)].append(n)
        return sorted(buckets.values(), key=len, reverse=True)

    # (a) Naive: every resolved edge. Expected to be one transcontinental hairball
    #     because editorial links chain A~B~C across the whole country — kept only
    #     to SHOW that naive connectivity can't define Nearby Groups.
    undirected_all = {tuple(sorted((s, t))) for (s, t) in directed}
    comps_all = components(undirected_all)

    # (b) Distance-gated: drop edges longer than _GROUP_MAX_KM so chains can't span
    #     regions. These components are the actionable proto-Nearby-Groups.
    dist_pairs = {
        tuple(sorted((e["source_id"], e["target_id"])))
        for e in edges
        if e["target_id"] and e["haversine_km"] is not None and e["haversine_km"] <= _GROUP_MAX_KM
    }
    comps_dist = components(dist_pairs)

    # (c) Reciprocal-only: mutual editorial links — the strongest "go together" signal.
    recip_pairs = {tuple(sorted((s, t))) for (s, t) in directed if (t, s) in directed}
    comps_recip = components(recip_pairs)

    def group_stats(comps: list[list[str]]) -> dict:
        sizes = [len(c) for c in comps]
        ge3 = [c for c in comps if len(c) >= 3]
        return {
            "n": len(comps),
            "ge3": len(ge3),
            "covered_ge3": sum(len(c) for c in ge3),
            "sizes": sizes,
            "comps": comps,
        }

    g_all = group_stats(comps_all)
    g_dist = group_stats(comps_dist)
    g_recip = group_stats(comps_recip)

    def id_by_title(substr: str) -> Optional[str]:
        target = _strip_accents(substr)
        matches = [_id for _id, rec in parsed.items()
                   if target in _strip_accents(rec["doc"].get("title") or "")]
        # Prefer a graph-connected node so the separation test is meaningful.
        for _id in matches:
            if _id in linked_nodes:
                return _id
        return matches[0] if matches else None

    omaha_id, arataki_id = id_by_title("Omaha"), id_by_title("Arataki")

    # Modularity (Louvain-style greedy) — the production-grade way to derive fine
    # Nearby Groups. Key test: does it separate Omaha (rural north) from Arataki
    # (Waitākere west), which distance-gating lumped into one 308-place Auckland blob?
    modularity_note = "networkx not installed — skipped"
    comm_separation = "n/a"
    try:
        import networkx as nx  # type: ignore
        G = nx.Graph()
        G.add_edges_from(undirected_all)
        comms = list(nx.algorithms.community.greedy_modularity_communities(G))
        comm_sizes = sorted((len(c) for c in comms), reverse=True)
        ge3 = [c for c in comms if len(c) >= 3]
        covered = sum(len(c) for c in ge3)
        cov_pct = (100.0 * covered / len(linked_nodes)) if linked_nodes else 0.0
        modularity_note = (
            f"{len(comms)} communities · {len(ge3)} with ≥3 (covering {covered} places, "
            f"{cov_pct:.1f}% of linked) · largest {comm_sizes[:8]}"
        )
        if omaha_id and arataki_id:
            o_comm = next((i for i, c in enumerate(comms) if omaha_id in c), None)
            a_comm = next((i for i, c in enumerate(comms) if arataki_id in c), None)
            same = o_comm is not None and o_comm == a_comm
            comm_separation = (
                f"Omaha & Arataki land in {'the SAME' if same else 'DIFFERENT'} communities "
                f"(sizes {len(comms[o_comm]) if o_comm is not None else '—'} / "
                f"{len(comms[a_comm]) if a_comm is not None else '—'})"
            )
    except Exception as exc:  # algo edge cases
        modularity_note = f"networkx run failed: {exc}"

    # Membership lookup for spot checks: id -> distance-gated group members (titles)
    id_to_distgroup: dict[str, list[str]] = {}
    for c in comps_dist:
        titles = sorted(parsed[m]["doc"].get("title", "") for m in c)
        for m in c:
            id_to_distgroup[m] = titles

    # isolated = has aiMetadata parsed but participates in zero resolved edges
    n_parseable = n_total - n_parse_error
    isolated_ids = [
        _id for _id, rec in parsed.items()
        if not rec["parsed"].parse_error and _id not in linked_nodes
    ]

    # ---- geometry divergence ----------------------------------------------
    _INREGION = {"exact", "fuzzy"}
    edge_kms = [e["haversine_km"] for e in edges
                if e["haversine_km"] is not None and e["method"] in _INREGION]
    far_edges = sorted(
        [e for e in edges if e["haversine_km"] and e["haversine_km"] > _FAR_EDGE_KM
         and e["method"] in _INREGION],
        key=lambda e: -e["haversine_km"],
    )
    # close-but-unlinked pairs (geometry over-suggests): O(n^2) over coord'd docs
    coord_docs = [(i, r["coords"]) for i, r in parsed.items() if r["coords"]]
    close_unlinked = 0
    close_examples: list[tuple[str, str, float]] = []
    for a in range(len(coord_docs)):
        ia, ca = coord_docs[a]
        for b in range(a + 1, len(coord_docs)):
            ib, cb = coord_docs[b]
            km = _haversine_km(ca[0], ca[1], cb[0], cb[1])
            if km <= _CLOSE_PAIR_KM:
                if ib not in adj.get(ia, ()) and ia not in adj.get(ib, ()):
                    close_unlinked += 1
                    if len(close_examples) < 12:
                        close_examples.append(
                            (parsed[ia]["doc"].get("title", ""), parsed[ib]["doc"].get("title", ""), round(km, 2))
                        )

    # ---- confidence / distance_text ---------------------------------------
    conf_present = sum(1 for e in edges if e["confidence"] is not None)
    dist_present = sum(1 for e in edges if e["distance_text"])

    # ---- spot checks (distance-gated group a place lands in) ---------------
    def distgroup_of(title_substr: str) -> list[str]:
        target = _strip_accents(title_substr)
        for _id, rec in parsed.items():
            if target in _strip_accents(rec["doc"].get("title") or ""):
                grp = id_to_distgroup.get(_id)
                if grp:
                    return grp[:20]
        return []

    spot_omaha = distgroup_of("Omaha")
    spot_arataki = distgroup_of("Arataki")

    # ---- write report ------------------------------------------------------
    tmp = _PKG_ROOT.parent / ".tmp"
    tmp.mkdir(exist_ok=True)
    pct = lambda a, b: f"{(100.0 * a / b):.1f}%" if b else "—"

    top_comps = comps_dist[:15]
    top_comp_lines = []
    for c in top_comps:
        titles = sorted(parsed[m]["doc"].get("title", "") for m in c)
        top_comp_lines.append(f"- **{len(c)} places**: {', '.join(titles[:10])}" + (" …" if len(titles) > 10 else ""))
    dist_size_hist = Counter(
        "3-5" if 3 <= s <= 5 else "6-10" if s <= 10 else "11-20" if s <= 20 else "21+"
        for s in g_dist["sizes"] if s >= 3
    )

    far_lines = [
        f"- {e['source_title']} → {e['target_name']} ({e['haversine_km']} km, {e['method']}"
        + (f", \"{e['distance_text']}\"" if e["distance_text"] else "") + ")"
        for e in far_edges[:12]
    ]
    close_lines = [f"- {a} ↔ {b} ({km} km, no editorial link)" for (a, b, km) in close_examples]

    if edge_kms:
        km_stats = (
            f"min {min(edge_kms):.1f} · median {statistics.median(edge_kms):.1f} · "
            f"p90 {sorted(edge_kms)[int(0.9 * len(edge_kms)) - 1]:.1f} · max {max(edge_kms):.1f}"
        )
    else:
        km_stats = "—"

    report = f"""# Editorial Nearby-Place Graph — Data Spike

_Read-only audit of `aiMetadata.nearby_places` across the corpus. No LLM/API tokens spent.
Name resolution: in-memory rapidfuzz `token_set_ratio` ≥ {_FUZZY_THRESHOLD} (same as the live tools)._

## 1. Corpus & coverage

| Metric | Value |
|---|---|
| Total `page` docs | {n_total} |
| With coordinates | {n_with_coords} ({pct(n_with_coords, n_total)}) |
| aiMetadata parse errors (truncated) | {n_parse_error} ({pct(n_parse_error, n_total)}) |
| Parseable docs | {n_parseable} |
| Docs with ≥1 editorial nearby link | {n_with_any} ({pct(n_with_any, n_total)}) |
| Docs card-ready (≥{_CARD_MIN_LINKS} links) | {n_card_ready} ({pct(n_card_ready, n_total)}) |

Link-count distribution: 0 → {link_counts['0']} · 1–2 → {link_counts['1-2']} · 3+ → {link_counts['3+']}

> Truncated docs ({n_parse_error}) lose their nearby_places to a JSON cap upstream — low coverage on
> those is a data-pipeline gap, not missing editorial intent.

## 2. Resolvability (the viability number)

| Edge outcome | Count | Share |
|---|---|---|
| Total editorial references | {n_edges} | 100% |
| Resolved — in-region exact | {n_resolved_exact} | {pct(n_resolved_exact, n_edges)} |
| Resolved — in-region fuzzy (≥{_FUZZY_THRESHOLD}) | {n_resolved_fuzzy} | {pct(n_resolved_fuzzy, n_edges)} |
| **Resolved in-region (trustworthy)** | **{n_inregion}** | **{pct(n_inregion, n_edges)}** |
| Resolved — cross-region fallback (suspect) | {n_xregion} | {pct(n_xregion, n_edges)} |
| Dangling (no corpus node) | {n_dangling} | {pct(n_dangling, n_edges)} |

_In-region matches resolve within the source place's own region, which kills the
cross-country name collisions (e.g. the several "Waipapa"s). Cross-region fallbacks are
mostly ambiguous-name mis-hits and are excluded from the corridor analysis below.
Dangling = the article names a place that isn't its own corpus page (a town, a region, a
non-page attraction) — can't become a graph edge without new nodes._

## 3. Graph shape

| Metric | Value |
|---|---|
| Directed edges (resolved, de-duped) | {len(directed)} |
| Nodes participating | {len(linked_nodes)} |
| Avg out-degree (linked nodes) | {avg_out:.2f} |
| Reciprocal edges (A→B and B→A) | {n_reciprocal} ({pct(n_reciprocal, len(directed))}) |
| **Isolated parseable docs (need curation/fallback)** | **{len(isolated_ids)}** ({pct(len(isolated_ids), n_parseable)}) |

### Deriving "Nearby Groups" — three clustering methods

Naive connectivity does **not** work: editorial links chain A~B~C across the whole
country, so all resolved edges collapse into **{g_all['n']} component(s)** (largest =
{g_all['sizes'][0] if g_all['sizes'] else 0}). Nearby Groups must come from a method that
resists transitive chaining:

| Method | Groups | Groups ≥3 | Places in a ≥3 group |
|---|---|---|---|
| Naive (all resolved edges) | {g_all['n']} | {g_all['ge3']} | {g_all['covered_ge3']} |
| **Distance-gated (≤{_GROUP_MAX_KM:.0f} km edges)** | {g_dist['n']} | **{g_dist['ge3']}** | **{g_dist['covered_ge3']}** ({pct(g_dist['covered_ge3'], len(linked_nodes))} of linked) |
| Reciprocal-only (mutual links) | {g_recip['n']} | {g_recip['ge3']} | {g_recip['covered_ge3']} |

Modularity (networkx greedy): {modularity_note}
Fine-group test: {comm_separation}

Distance-gated group-size spread (≥3): {', '.join(f'{k}: {v}' for k, v in sorted(dist_size_hist.items())) or '—'}

### Largest distance-gated proto-groups
{chr(10).join(top_comp_lines) if top_comp_lines else '_none_'}

### Spot checks (distance-gated group the place lands in)
- **Omaha** ({len(spot_omaha)}): {', '.join(spot_omaha) if spot_omaha else 'not in a ≥2 group'}
- **Arataki** ({len(spot_arataki)}): {', '.join(spot_arataki) if spot_arataki else 'not in a ≥2 group'}

## 4. Geometry divergence (value over haversine)

Resolved-edge straight-line distance (km): {km_stats}

**Editorial links >{_FAR_EDGE_KM:.0f} km apart** ({len(far_edges)} total) — corridor/road knowledge pure distance can't see:
{chr(10).join(far_lines) if far_lines else '_none_'}

**Close pairs (<{_CLOSE_PAIR_KM:.0f} km) with NO editorial link** ({close_unlinked} pairs) — where geometry over-suggests
(includes across-water / across-valley cases editorial deliberately omits):
{chr(10).join(close_lines) if close_lines else '_none_'}

## 5. Editorial signal richness

| Field | Present on edges | Share |
|---|---|---|
| `confidence` | {conf_present} | {pct(conf_present, n_edges)} |
| `distance_text` | {dist_present} | {pct(dist_present, n_edges)} |

_`distance_text` is a free editorial proximity proxy needing no routing API._

---
_Raw edges: `.tmp/nearby_graph_edges.json`_
"""

    out_md = tmp / "nearby_graph_spike.md"
    out_md.write_text(report, encoding="utf-8")
    (tmp / "nearby_graph_edges.json").write_text(
        json.dumps(edges, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # ---- stdout summary (ASCII-only: Windows console is cp1252) -------------
    print(f"\nReport -> {out_md}")
    print(f"Corpus: {n_total} docs | {n_with_any} with editorial links | {n_card_ready} card-ready (>={_CARD_MIN_LINKS})")
    print(f"Edges: {n_edges} refs | {pct(n_resolved, n_edges)} resolve | {pct(n_dangling, n_edges)} dangle")
    print(f"Graph: {len(directed)} edges | {pct(n_reciprocal, len(directed))} reciprocal | "
          f"naive comps={g_all['n']} | dist-gated groups>=3={g_dist['ge3']} | {len(isolated_ids)} isolated docs")
    print(f"Divergence: {len(far_edges)} far editorial links | {close_unlinked} close-but-unlinked pairs")


if __name__ == "__main__":
    main()
