"""Discovery script — inspects the Tripideas Sanity corpus.

Verifies connectivity, lists document types, samples docs of each
content-bearing type to find which carry the editorial `metadata` field
and where (root.tags vs metadata.tags) tags live.

Run:
    python execution/inspect_corpus.py
"""

from __future__ import annotations

import json
import sys
from collections import Counter

from sanity_client import SanityClient

# Windows console defaults to cp1252 — reconfigure for Māori macrons etc.
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, OSError):
        pass


def header(text: str) -> None:
    print(f"\n--- {text} ---")


def main() -> None:
    client = SanityClient()
    print(f"Connected to project={client.project_id} dataset={client.dataset} "
          f"api={client.api_version} perspective={client.default_perspective}")

    header("Document types and counts")
    types = client.list_document_types(limit=100) or []
    counts: dict[str, int] = {}
    for doc_type in types:
        counts[doc_type] = client.query("count(*[_type == $t])", params={"t": doc_type})
    for t, c in sorted(counts.items(), key=lambda x: -x[1]):
        print(f"  {t:24s} {c}")

    header("`tag` doc — what does the tag taxonomy look like?")
    tag_docs = client.query("*[_type == 'tag'][0...5]{...}")
    print(json.dumps(tag_docs, indent=2, ensure_ascii=False)[:2000])
    all_tag_titles = client.query("*[_type == 'tag']{_id, title, name, slug, category}") or []
    print(f"\n  Total tag docs: {len(all_tag_titles)}")
    sample_titles = [d.get("title") or d.get("name") or d.get("slug", {}).get("current")
                     for d in all_tag_titles[:30] if d]
    print(f"  Sample titles: {sample_titles}")

    header("`region` doc shape")
    region_sample = client.query("*[_type == 'region'][0...3]{...}")
    print(json.dumps(region_sample, indent=2, ensure_ascii=False)[:1500])

    header("`subRegion` doc shape")
    sub_sample = client.query("*[_type == 'subRegion'][0...3]{...}")
    print(json.dumps(sub_sample, indent=2, ensure_ascii=False)[:1500])

    header("Content-bearing types — which carry `metadata`?")
    content_types = ["route", "page", "post", "accommodation"]
    for doc_type in content_types:
        if doc_type not in counts:
            continue
        with_metadata = client.query(
            "count(*[_type == $t && defined(metadata)])", params={"t": doc_type}
        )
        with_root_tags = client.query(
            "count(*[_type == $t && defined(tags) && length(tags) > 0])",
            params={"t": doc_type},
        )
        print(f"  {doc_type}: {counts[doc_type]} total, "
              f"{with_metadata} with metadata, {with_root_tags} with root.tags")

    header("Sample `route` (top-level + metadata + dereferenced tags)")
    route = client.fetch_one(
        '*[_type == "route"][0]{..., "tag_titles": tags[]->title, '
        '"region_title": region->title, "subRegion_title": subRegion->title}'
    )
    if route:
        print(f"  Top-level keys: {sorted(route.keys())}")
        print(f"  title: {route.get('title')}")
        print(f"  region_title: {route.get('region_title')}")
        print(f"  subRegion_title: {route.get('subRegion_title')}")
        print(f"  tag_titles: {route.get('tag_titles')}")
        if isinstance(route.get("metadata"), dict):
            md = route["metadata"]
            print(f"  metadata keys: {sorted(md.keys())}")
            md_tags = md.get("tags")
            print(f"  metadata.tags ({type(md_tags).__name__}): "
                  f"{md_tags[:8] if isinstance(md_tags, list) else md_tags}")

    header("Sample `page` (any, no metadata filter)")
    page = client.fetch_one(
        '*[_type == "page"][0]{..., "tag_titles": tags[]->title}'
    )
    if page:
        print(f"  Top-level keys: {sorted(page.keys())}")
        print(f"  title: {page.get('title')}")
        print(f"  tag_titles: {page.get('tag_titles')}")
        # Print the body shape (first 200 chars)
        body = page.get("body")
        print(f"  body type: {type(body).__name__}, "
              f"sample: {str(body)[:200] if body else 'None'}")

    header("Does ANY published doc have `metadata`?")
    types_with_md = {}
    for doc_type in ["page", "post", "route", "accommodation"]:
        count_md = client.query(
            "count(*[_type == $t && defined(metadata)])", params={"t": doc_type}
        )
        types_with_md[doc_type] = count_md
    print(f"  Per type with metadata (published): {types_with_md}")

    header("Same check via perspective=raw (drafts included)")
    for doc_type in ["page", "post", "route", "accommodation"]:
        count_md = client.query(
            "count(*[_type == $t && defined(metadata)])",
            params={"t": doc_type},
            perspective="raw",
        )
        print(f"  {doc_type} with metadata (raw): {count_md}")

    header("Full live tag list (all 102)")
    all_tags = client.query("*[_type == 'tag']{name, slug, color} | order(name asc)") or []
    for t in all_tags:
        print(f"  {t.get('name')!r:40s} slug={t.get('slug', {}).get('current')!r}")
    print(f"  Total: {len(all_tags)}")

    header("Page → route relationships (do pages reference routes?)")
    page_with_route_ref = client.query(
        "count(*[_type == 'page' && (count(routes) > 0 || defined(route))])"
    )
    print(f"  Pages with route references: {page_with_route_ref}")
    sample_page_with_routes = client.fetch_one(
        '*[_type == "page" && count(routes) > 0][0]{title, "route_count": count(routes), '
        '"first_route_name": routes[0]->name}'
    )
    print(f"  Sample: {sample_page_with_routes}")

    header("Sample `accommodation`")
    accom = client.fetch_one(
        '*[_type == "accommodation"][0]{..., "tag_titles": tags[]->title}'
    )
    if accom:
        print(f"  Top-level keys: {sorted(accom.keys())}")
        print(f"  title: {accom.get('title')}")
        if isinstance(accom.get("metadata"), dict):
            print(f"  metadata keys: {sorted(accom['metadata'].keys())}")
        else:
            print(f"  metadata: {accom.get('metadata')}")
        print(f"  tag_titles: {accom.get('tag_titles')}")


if __name__ == "__main__":
    main()
