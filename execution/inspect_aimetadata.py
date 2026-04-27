"""Quick check on the `aiMetadata` field — its presence, shape, and content."""

from __future__ import annotations

import json
import sys

from sanity_client import SanityClient

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, OSError):
        pass


def main() -> None:
    client = SanityClient()

    print("--- aiMetadata coverage by content type ---")
    for doc_type in ["page", "post", "route", "accommodation"]:
        total = client.query("count(*[_type == $t])", params={"t": doc_type})
        with_ai = client.query(
            "count(*[_type == $t && defined(aiMetadata)])", params={"t": doc_type}
        )
        print(f"  {doc_type}: {with_ai}/{total} have aiMetadata")

    print("\n--- Sample page with aiMetadata, dereferenced refs ---")
    page = client.fetch_one(
        '*[_type == "page" && defined(aiMetadata)][0]{'
        '_id, title, coordinates, '
        '"tag_names": tags[]->name, '
        '"subRegion_name": subRegion->name, '
        '"region_name": subRegion->region->name, '
        'aiMetadata'
        '}'
    )
    if not page:
        print("  No pages with aiMetadata!")
        return
    print(f"  _id: {page.get('_id')}")
    print(f"  title: {page.get('title')}")
    print(f"  coordinates: {page.get('coordinates')}")
    print(f"  region_name: {page.get('region_name')}")
    print(f"  subRegion_name: {page.get('subRegion_name')}")
    print(f"  tag_names: {page.get('tag_names')}")
    ai = page.get("aiMetadata")
    if isinstance(ai, dict):
        print(f"  aiMetadata keys: {sorted(ai.keys())}")
        # Show one or two interesting nested fields
        for k in ("location", "themes", "activities", "tags"):
            if k in ai:
                v = ai[k]
                if isinstance(v, (list, dict)):
                    print(f"  aiMetadata.{k}: {json.dumps(v, ensure_ascii=False)[:200]}")
                else:
                    print(f"  aiMetadata.{k}: {v}")

    print("\n--- Other potentially place-linking fields on pages ---")
    page_keys_freq = client.query(
        '*[_type == "page" && defined(aiMetadata)][0...100]{'
        '"keys": coalesce(*[_id == ^._id]._type, []),'
        '_id, _type'
        '}'
    )
    # Try to find pages that reference routes via different field names
    for field_name in ["routes", "relatedRoutes", "tracks", "walks", "trails", "linkedRoutes"]:
        count = client.query(
            f"count(*[_type == 'page' && count({field_name}) > 0])"
        )
        if count:
            print(f"  Pages with {field_name}: {count}")
        else:
            print(f"  Pages with {field_name}: 0")


if __name__ == "__main__":
    main()
