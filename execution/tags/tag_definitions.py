"""Working definitions + keyword stems for the 15 underused tags.

Used by:
  - `find_underused_tag_candidates.py` — for the cheap regex pre-filter and
    as the source of definitions injected into the Claude prompt.

Each entry has:
  - `name`: exact tag name in Sanity (matches the resolved tag doc)
  - `definition`: one-line working definition the LLM (and any human reviewer)
    should apply when judging a fit. Calibrated to the corpus context
    (NZ travel articles, place-page format).
  - `positive_keywords`: regex stems that indicate the tag *might* apply.
    Pre-filter passes an article if ANY of these match anywhere in the
    aiMetadata text + title + description. Cast wide here — Claude does
    the final yes/no.
  - `negative_signals`: optional. Patterns that should make Claude
    hesitate (e.g., "Boat Access" should NOT apply when "by boat only"
    is just trivia rather than the actual access method). Used only in
    the LLM prompt, not in pre-filter.
"""

from __future__ import annotations

TAG_DEFINITIONS: list[dict] = [
    # '4WD Access' entry retired 2026-06-18. Douglas confirmed the tag has
    # been split into:
    #   - 'Gravel Roads' (apply when access is unsealed/gravel — most cases
    #     the old '4WD Access' was wrongly used for).
    #   - '4WD Recommended' (forthcoming — definition TBD with Douglas) for
    #     places where a 4WD genuinely makes a difference.
    # The old definition's positive_keywords correctly flagged gravel-road
    # access ("\bgravel road\b" etc.) but the conclusion "4WD Access" was
    # almost always wrong — confirmed root cause of Douglas's over-application
    # complaint. Re-tag pass will rebuild from canonical 86 tags including
    # the new replacements.
    {
        "name": "Beech Forests",
        "definition": (
            "The article features beech forest as a notable habitat — silver, "
            "red, mountain, hard, or black beech (Nothofagus / Fuscospora / "
            "Lophozonia). Generic 'forest' or 'native bush' alone does NOT "
            "qualify. Articles featuring kauri or podocarp forest specifically "
            "do not get this tag."
        ),
        "positive_keywords": [
            r"\bbeech\b",
            r"\bnothofagus\b",
            r"\bfuscospora\b",
            r"\bsilver beech\b",
            r"\bred beech\b",
            r"\bmountain beech\b",
            r"\bhard beech\b",
            r"\bblack beech\b",
        ],
        "negative_signals": [],
    },
    {
        "name": "Biosecurity Access",
        "definition": (
            "Visitors must follow biosecurity protocols to enter — typically "
            "shoe-cleaning stations for kauri dieback, didymo / freshwater pest "
            "checks, or pest-free island arrival inspections. Casual 'leave no "
            "trace' messaging is NOT enough."
        ),
        "positive_keywords": [
            r"\bbiosecurity\b",
            r"\bkauri dieback\b",
            r"\bdidymo\b",
            r"\bcheck[, ]+clean[, ]+dry\b",
            r"\bshoe[- ]?clean(ing)?\b",
            r"\bcleaning station\b",
            r"\bpest[- ]?free island\b",
            r"\bquarantine\b",
        ],
        "negative_signals": [],
    },
    {
        "name": "Boat Access",
        "definition": (
            "The primary or only practical way to reach the place is by boat — "
            "water taxi, kayak, ferry to a remote landing. Excludes places that "
            "merely have a boat ramp or where boating is a leisure activity but "
            "road access exists."
        ),
        "positive_keywords": [
            r"\bboat access\b",
            r"\bwater taxi\b",
            r"\bonly accessible by boat\b",
            r"\baccessible by boat\b",
            r"\baccessible only by\b",
            r"\bboat[- ]?in\b",
            r"\bkayak[- ]?in\b",
            r"\bferry\b",
            r"\bdinghy\b",
        ],
        "negative_signals": [
            "boat ramp",
            "popular for boating",
        ],
    },
    {
        "name": "Caves",
        "definition": (
            "The article features one or more caves (limestone, karst, lava "
            "tube, glow-worm cave). Sea Caves get the existing 'Sea Caves' tag, "
            "not this one — apply 'Caves' only to inland/non-marine caves."
        ),
        "positive_keywords": [
            r"\bcave[s]?\b",
            r"\bcaving\b",
            r"\bglow[- ]?worm\b",
            r"\bglowworm\b",
            r"\bkarst\b",
            r"\blimestone cave\b",
            r"\blava tube\b",
            r"\bstalactite\b",
            r"\bstalagmite\b",
            r"\bspeleolog\b",
        ],
        "negative_signals": [
            "sea cave",  # use 'Sea Caves' tag for those
        ],
    },
    {
        "name": "City Parks",
        "definition": (
            "An urban public park within a city (population ~50k+ — e.g., "
            "Auckland, Wellington, Christchurch, Hamilton, Tauranga, Dunedin, "
            "Palmerston North, Napier). Distinct from 'Town Parks' (smaller "
            "settlements) and 'Regional Parks' (DOC-managed regional reserves)."
        ),
        "positive_keywords": [
            r"\bpark\b",
            r"\bdomain\b",
            r"\bgardens\b",
            r"\bcity\b",
            r"\bauckland\b",
            r"\bwellington\b",
            r"\bchristchurch\b",
            r"\bhamilton\b",
            r"\btauranga\b",
            r"\bdunedin\b",
            r"\bnapier\b",
            r"\bpalmerston north\b",
        ],
        "negative_signals": [
            "regional park",
            "national park",
        ],
    },
    {
        "name": "Freedom Camping",
        "definition": (
            "Freedom camping (self-contained-vehicle camping, often roadside or "
            "in council-designated freedom-camping areas) is permitted at or "
            "near the place. Paid campgrounds and DOC campsites do NOT qualify "
            "for this tag."
        ),
        "positive_keywords": [
            r"\bfreedom camping\b",
            r"\bself[- ]?contained\b",
            r"\bovernight in vehicle\b",
            r"\bcamper van\b",
            r"\bcampervan\b",
            r"\bmotorhome\b",
        ],
        "negative_signals": [
            "no freedom camping",
            "freedom camping prohibited",
            "doc campsite",
        ],
    },
    {
        "name": "Glaciers",
        "definition": (
            "The article features a glacier — Franz Josef, Fox, Tasman, "
            "Murchison, Hooker, or any other ice body or glacial feature you "
            "can see/walk on/up to. Articles that just mention 'glacial valley' "
            "or 'glacial lake' without an active glacier itself do NOT qualify."
        ),
        "positive_keywords": [
            r"\bglacier[s]?\b",
            r"\bice field\b",
            r"\bicefield\b",
            r"\bfranz josef\b",
            r"\bfox glacier\b",
            r"\btasman glacier\b",
            r"\bhooker glacier\b",
            r"\bmurchison glacier\b",
            r"\bcrevasse\b",
            r"\bmoraine\b",  # weaker signal but worth catching
        ],
        "negative_signals": [
            "glacial lake",  # only — not a glacier itself
            "glacial valley",
            "glacial origin",
        ],
    },
    # 'Historical Trails' entry retired 2026-06-18. Canonical Sanity tag is
    # 'Heritage Trails' — the live taxonomy doesn't carry a separate
    # 'Historical Trails' concept. The keyword stems (gold-mining, coach
    # road, tramway, etc.) are still valuable signals — they'll roll into
    # the 'Heritage Trails' definition when we extend tag_definitions.py
    # to all 86 tags in Workstream B1.
    {
        "name": "Māori History",
        "definition": (
            "The article features Māori history, culture, or significance — "
            "iwi connections, marae, pā sites, wāhi tapu, named whakapapa, "
            "carved pou, named atua/tūpuna, or substantive cultural narrative. "
            "Just having a Māori place-name does NOT qualify; there must be "
            "meaningful cultural-historical content."
        ),
        "positive_keywords": [
            r"\bm[āa]ori\b",
            r"\biwi\b",
            r"\bmarae\b",
            r"\bp[āa] site\b",
            r"\bp[āa]\b",
            r"\bwh[āa]nau\b",
            r"\bwh[āa]kapapa\b",
            r"\btangata whenua\b",
            r"\bwh[āa]i tapu\b",
            r"\bw[āa]hi tapu\b",
            r"\bhap[ūu]\b",
            r"\btaonga\b",
            r"\bpou\b",
            r"\bmana whenua\b",
            r"\bt[ūu]puna\b",
            r"\bancestor\b",  # weaker
            r"\btreaty of waitangi\b",
        ],
        "negative_signals": [],
    },
    {
        "name": "Night Walks",
        "definition": (
            "A walk/track best done after dark — glow-worm trails, "
            "kiwi-spotting walks, stargazing trails, dark-sky access tracks. "
            "Day-walks that 'can also be done at night' do NOT qualify — must "
            "be a place where night is the intended/featured experience."
        ),
        "positive_keywords": [
            r"\bnight walk\b",
            r"\bafter dark\b",
            r"\bglow[- ]?worm walk\b",
            r"\bkiwi spotting\b",
            r"\bkiwi[- ]?spotting\b",
            r"\bstargaz\b",
            r"\bdark sky\b",
            r"\bnight tour\b",
            r"\btorch\b",
            r"\bnocturnal\b",
        ],
        "negative_signals": [],
    },
    {
        "name": "Restoration Sites",
        "definition": (
            "An active ecological restoration project — community-led pest "
            "removal, replanting programmes, wildlife sanctuaries with active "
            "predator control, wetland restoration. Mature DOC reserves with "
            "no current restoration work do NOT qualify."
        ),
        "positive_keywords": [
            r"\brestoration\b",
            r"\bpredator[- ]?free\b",
            r"\bpest[- ]?free\b",
            r"\breplanting\b",
            r"\brevegetation\b",
            r"\bsanctuary\b",
            r"\bwetland restoration\b",
            r"\btrapping\b",
            r"\bcommunity[- ]?led\b",
            r"\bconservation project\b",
            r"\becosanctuary\b",
        ],
        "negative_signals": [],
    },
    {
        "name": "Seasonal Access",
        "definition": (
            "Access is restricted by season — closed in winter, summer-only "
            "alpine routes, lambing closures, breeding-season restrictions. "
            "Tides count if the entire place is tidally locked (e.g., walkable "
            "only at low tide). Weather-dependent advisories alone do NOT "
            "qualify."
        ),
        "positive_keywords": [
            r"\bseasonal\b",
            r"\bclosed in winter\b",
            r"\bclosed for winter\b",
            r"\bsummer only\b",
            r"\bwinter only\b",
            r"\blambing\b",
            r"\bbreeding season\b",
            r"\bonly accessible at low tide\b",
            r"\blow tide only\b",
            r"\bclosed [a-z]+ to [a-z]+\b",  # e.g., "closed June to October"
            r"\bopen [a-z]+ to [a-z]+\b",
            r"\bavalanche season\b",
        ],
        "negative_signals": [],
    },
    {
        "name": "Surfing",
        "definition": (
            "The article features a surf spot or surf beach. Generic beaches "
            "where surfing isn't a named activity do NOT qualify. Look for "
            "named breaks, surf-school references, surf-specific gear talk."
        ),
        "positive_keywords": [
            r"\bsurf\b",
            r"\bsurfing\b",
            r"\bsurf[- ]?break\b",
            r"\bsurf[- ]?spot\b",
            r"\bsurf beach\b",
            r"\bswell\b",
            r"\bsurf[- ]?school\b",
            r"\bsurfboard\b",
            r"\bbeginner waves\b",
            r"\bbarrel\b",
            r"\bpoint break\b",
            r"\bbeach break\b",
        ],
        "negative_signals": [
            "no surf",
            "not safe for swimming",  # might still be surf
        ],
    },
    {
        "name": "Town Parks",
        "definition": (
            "A public park in a smaller town/settlement (population under ~50k) "
            "— e.g., Whakatane, Greymouth, Picton, Twizel, Te Anau, Methven. "
            "Distinct from 'City Parks' (large cities) and 'Regional Parks' "
            "(DOC-managed reserves outside towns)."
        ),
        "positive_keywords": [
            r"\bpark\b",
            r"\bdomain\b",
            r"\bgardens\b",
            r"\bsquare\b",
            r"\breserve\b",
            r"\bvillage green\b",
        ],
        "negative_signals": [
            "regional park",
            "national park",
            "auckland",
            "wellington",
            "christchurch",
            # negatives are city names — applied in LLM prompt only
        ],
    },
    # ---------------------------------------------------------------------
    # New tags pending Douglas creating them in Sanity (2026-06-18). Drafted
    # definitions framed by chatbot use case — Sam approved this wording.
    # Once Douglas creates each tag in Sanity, the tag_mapping_parity audit
    # will go clean.
    # ---------------------------------------------------------------------
    {
        "name": "4WD Recommended",
        "definition": (
            "A 2WD passenger car can make the trip in dry conditions, but a "
            "4WD or AWD vehicle is genuinely useful — better clearance, "
            "traction in wet, snow line, river fords, slippery clay tracks. "
            "Distinct from places where 4WD is strictly required (those go "
            "in description as a hard warning, not this tag). Distinct from "
            "'Gravel Roads' which is purely about unsealed surfaces that any "
            "2WD car copes with in fine weather. The chatbot uses this as a "
            "soft advisory ('consider a 4WD'), not a hard exclusion."
        ),
        "positive_keywords": [
            r"\b4wd\b",
            r"\b4-?wheel[- ]?drive\b",
            r"\bfour[- ]?wheel[- ]?drive\b",
            r"\bawd\b",
            r"\b4x4\b",
            r"\bhigh clearance\b",
            r"\briver crossing\b",
            r"\bford(?:ing)? the\b",
            r"\bslippery (?:clay|track|road)\b",
            r"\bsnow chains? (?:required|recommended)\b",
        ],
        "negative_signals": [
            "sealed road right to the door",
            "accessible by 2WD",
            "2WD friendly",
            # 'gravel road' alone does NOT trigger this — that's 'Gravel Roads'
        ],
    },
    {
        "name": "Seasonal Access for Roads",
        "definition": (
            "Vehicle access to the place is restricted or unsafe for part of "
            "the year — winter snow closures (Crown Range Road, Milford Road "
            "alerts), snow gates that close overnight or in storms, road "
            "sections regularly slip-prone after heavy rain, washout-prone "
            "fords, ferry-only access with seasonal schedules. The chatbot "
            "uses this to filter out the place for trips in the restricted "
            "season, or to surface a 'check road status / NZTA Journey "
            "Planner before you go' caveat otherwise. Distinct from "
            "'Seasonal Access for Trails' (foot/track access) and the "
            "generic 'Seasonal Access' (which we may retire once these two "
            "are in)."
        ),
        "positive_keywords": [
            r"\bsnow gate\b",
            r"\bsnow chains? required\b",
            r"\bsnow chains? recommended\b",
            r"\broad closure\b",
            r"\bwinter closure\b",
            r"\bclosed (?:in )?winter\b",
            r"\bcrown range\b",
            r"\bmilford road\b",
            r"\bslip[- ]?prone\b",
            r"\bwashout\b",
            r"\bseasonal ferry\b",
            r"\bsummer only road\b",
            r"\bavalanche risk\b.*\broad\b",
        ],
        "negative_signals": [
            # walking-only seasonality belongs in 'Seasonal Access for Trails'
            "track closed in winter",
            "alpine track season",
        ],
    },
    {
        "name": "Seasonal Access for Trails",
        "definition": (
            "Walking/tramping access to the place is restricted or unsafe for "
            "part of the year — alpine sections closed by avalanche risk "
            "(Routeburn, Greenstone alpine portions), river crossings unsafe "
            "in spring melt, boggy and impassable in winter, kauri-dieback "
            "rāhui, lambing closures on private-easement tracks, breeding "
            "season closures (sea bird colonies, fur seals). The chatbot uses "
            "this to filter the place out for trips in the restricted season, "
            "or to surface a 'check track status / DOC alert' caveat. "
            "Distinct from 'Seasonal Access for Roads' (vehicle access) and "
            "the generic 'Seasonal Access' (which we may retire once these "
            "two are in)."
        ),
        "positive_keywords": [
            r"\bavalanche\b",
            r"\bavalanche season\b",
            r"\balpine season\b",
            r"\bclosed (?:in )?winter\b",
            r"\bclosed for winter\b",
            r"\briver crossing\b.*\b(?:flood|unsafe|spring)",
            r"\bspring melt\b",
            r"\bboggy\b",
            r"\brāhui\b",
            r"\brahui\b",
            r"\bkauri dieback\b.*\bclosure\b",
            r"\blambing\b",
            r"\bbreeding season\b",
            r"\bbird (?:nesting|breeding)\b",
            r"\bfur seal (?:breeding|colony closure)\b",
        ],
        "negative_signals": [
            # vehicle-only seasonality belongs in 'Seasonal Access for Roads'
            "snow gate",
            "road closure",
            "winter road",
        ],
    },
]


TAG_NAMES_15: list[str] = [t["name"] for t in TAG_DEFINITIONS]


def get_definition(name: str) -> dict | None:
    for t in TAG_DEFINITIONS:
        if t["name"] == name:
            return t
    return None


if __name__ == "__main__":
    # Sanity-check: print each definition + keyword count
    for t in TAG_DEFINITIONS:
        print(f"\n{t['name']}")
        print(f"  def: {t['definition']}")
        print(f"  positives: {len(t['positive_keywords'])} keywords")
        print(f"  negatives: {len(t['negative_signals'])} keywords")
