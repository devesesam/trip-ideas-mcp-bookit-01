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
        "name": "Alpine Routes",
        "definition": (
            "Above-bushline mountaineering or alpine traverses that require "
            "snow/ice/rope skills beyond ordinary tramping — Mt Cook / Aspiring "
            "summit routes, alpine traverses, snow grade or higher classified "
            "routes. Ordinary alpine huts or tussock-zone walks do NOT qualify "
            "(those are Tramps or High Country)."
        ),
        "positive_keywords": [
            r"\balpine route\b",
            r"\balpine traverse\b",
            r"\bmountaineer\b",
            r"\bsnow grade\b",
            r"\balpine grade\b",
            r"\bice route\b",
            r"\bcrampon\b",
            r"\brope[- ]?work\b",
            r"\bexposed ridge\b",
            r"\bsummit traverse\b",
            r"\bglacier route\b",
        ],
        "negative_signals": [
            "alpine garden",   # botanical, not climbing
            "alpine hut only", # just accommodation
        ],
    },
    {
        "name": "Architecture",
        "definition": (
            "The place is notable for its built design — heritage homesteads, "
            "art deco precincts, modernist civic buildings, distinctive religious "
            "architecture, named architects, named architectural styles. Generic "
            "'old building' or 'historic building' without architectural merit "
            "should go to Historic Sites instead."
        ),
        "positive_keywords": [
            r"\barchitecture\b",
            r"\barchitect\b",
            r"\bart deco\b",
            r"\bvictorian\b",
            r"\bedwardian\b",
            r"\bmodernist\b",
            r"\bgothic\b",
            r"\bromanesque\b",
            r"\bdesigned by\b",
            r"\bfa[çc]ade\b",
            r"\bheritage building\b",
        ],
        "negative_signals": [
            "ruins",
            "collapsed",
        ],
    },
    {
        "name": "Art Galleries",
        "definition": (
            "Public or commercial visual-arts gallery — exhibitions, collections, "
            "named artists, programmed shows. Outdoor sculpture trails are "
            "'Public Art and Sculpture'; museums with primarily historical or "
            "natural-history content are 'Museums'."
        ),
        "positive_keywords": [
            r"\bart gallery\b",
            r"\bart galleries\b",
            r"\bexhibition\b",
            r"\bcontemporary art\b",
            r"\bdealer gallery\b",
            r"\bpainter\b",
            r"\bcurator\b",
            r"\bsolo show\b",
            r"\bart space\b",
        ],
        "negative_signals": [
            "sculpture trail",   # use 'Public Art and Sculpture'
            "natural history museum",
        ],
    },
    {
        "name": "Backcountry Huts",
        "definition": (
            "DOC- or club-managed huts in remote tramping areas — serviced, "
            "standard, basic, or bivvy classifications. Holiday parks, lodges, "
            "motels, and frontcountry cabins are NOT this tag."
        ),
        "positive_keywords": [
            r"\bbackcountry hut\b",
            r"\bdoc hut\b",
            r"\balpine hut\b",
            r"\bserviced hut\b",
            r"\bstandard hut\b",
            r"\bbasic hut\b",
            r"\btramping hut\b",
            r"\bbunk room\b",
            r"\bhut ticket\b",
            r"\bbivvy\b",
            r"\bbivouac\b",
        ],
        "negative_signals": [
            "lodge",
            "motel",
            "holiday park",
            "self-contained cabin",
        ],
    },
    {
        "name": "Beaches",
        "definition": (
            "Any sand or pebble beach worth visiting — surf beach, swimming bay, "
            "shellfish-foraging stretch, beachcombing coast, pōhutukawa-fringed "
            "cove. Sea cliffs without an adjoining beach are 'Cliffs', not this "
            "tag."
        ),
        "positive_keywords": [
            r"\bbeach\b",
            r"\bsand\b",
            r"\bdune\b",
            r"\bwhite sand\b",
            r"\bblack sand\b",
            r"\bshell beach\b",
            r"\bpebble beach\b",
            r"\bbay\b",
            r"\bcove\b",
            r"\bfor[e]?shore\b",
            r"\bp[ōo]hutukawa\b",
        ],
        "negative_signals": [],
    },
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
        "name": "Bird Sanctuaries",
        "definition": (
            "An actively managed bird sanctuary — fenced ecosanctuary, "
            "predator-free mainland island, or pest-free island reserve with "
            "named threatened-species programmes (kākāpō, kiwi, tīeke, kōkako, "
            "hihi). Casual bird-watching sites without active conservation "
            "management belong in 'Wildlife Encounters'."
        ),
        "positive_keywords": [
            r"\bbird sanctuary\b",
            r"\bsanctuary\b",
            r"\bpredator[- ]?free\b",
            r"\bpest[- ]?free island\b",
            r"\bmainland island\b",
            r"\bfenced sanctuary\b",
            r"\bzealandia\b",
            r"\btiritiri\b",
            r"\bk[āa]k[āa]p[ōo]\b",
            r"\bkiwi sanctuary\b",
            r"\bt[īi]eke\b",
            r"\bk[ōo]k[āa]ko\b",
        ],
        "negative_signals": [
            "casual bird watching",
        ],
    },
    {
        "name": "Boardwalks",
        "definition": (
            "A built timber or composite walkway over fragile terrain — peat "
            "bog, geothermal mud field, dune system, wetland margin. Usually "
            "stepfree, often wheelchair-accessible. Generic raised platforms "
            "or short viewing decks do NOT qualify on their own."
        ),
        "positive_keywords": [
            r"\bboardwalk\b",
            r"\braised walkway\b",
            r"\bwooden platform\b",
            r"\bwheelchair[- ]?accessible\b",
            r"\bstepfree\b",
            r"\bstep[- ]?free\b",
            r"\baccessible track\b",
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
        "name": "Botanic Gardens",
        "definition": (
            "A curated botanical collection with named species, themed beds, or "
            "horticultural significance — Auckland Domain glasshouses, "
            "Christchurch Botanic Gardens, Otago herb garden. Ordinary town "
            "parks with grass and roses don't qualify (those are Town Parks or "
            "City Parks)."
        ),
        "positive_keywords": [
            r"\bbotanic garden\b",
            r"\bbotanical garden\b",
            r"\bconservatory\b",
            r"\brose garden\b",
            r"\bherb garden\b",
            r"\bglasshouse\b",
            r"\brhododendron\b",
            r"\bcamellia\b",
            r"\bcurated planting\b",
        ],
        "negative_signals": [
            "domain",  # usually a Town Park / City Park
            "ornamental garden",  # private
        ],
    },
    {
        "name": "Camping",
        "definition": (
            "The place supports camping in some form (tent, vehicle, holiday "
            "park). For DOC-specific sites use 'DOC Campsites'; for freedom "
            "camping use the 'Freedom Camping' tag — this generic tag is for "
            "places that mention camping is permitted/available without "
            "fitting those specific sub-categories."
        ),
        "positive_keywords": [
            r"\bcamp\b",
            r"\bcampsite\b",
            r"\btent site\b",
            r"\bcamping ground\b",
            r"\bholiday park\b",
            r"\bmotorhome park\b",
            r"\bcamper park\b",
        ],
        "negative_signals": [
            "no camping",
            "day use only",
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
        "name": "Cliff Walks",
        "definition": (
            "A walking track that runs along clifftops or the edge of cliffs — "
            "Wellington South Coast clifftops, Whangārei Heads coastal scarp, "
            "Cathedral Cliffs walkway. Weather-exposed and often unsuitable in "
            "high wind."
        ),
        "positive_keywords": [
            r"\bclifftop\b",
            r"\bcliff walk\b",
            r"\bcliff[- ]?top\b",
            r"\bcoastal cliff\b",
            r"\bsea cliff\b",
            r"\bheadland walk\b",
            r"\bscarp\b",
            r"\bexposed cliff\b",
        ],
        "negative_signals": [],
    },
    {
        "name": "Cliffs",
        "definition": (
            "Cliffs are themselves the feature — sheer escarpments, headlands, "
            "columnar basalts, fjord walls, inland gorges. Apply whether viewed "
            "from above or below. Beaches with cliffs in the background should "
            "stay 'Beaches' unless the cliffs are a stated destination."
        ),
        "positive_keywords": [
            r"\bcliff\b",
            r"\bcliffs\b",
            r"\bsheer drop\b",
            r"\bvertical drop\b",
            r"\bescarpment\b",
            r"\bgorge wall\b",
            r"\bheadland\b",
            r"\bsea cliff\b",
            r"\brock face\b",
            r"\bcolumnar\b",
        ],
        "negative_signals": [],
    },
    {
        "name": "Coastal Walks",
        "definition": (
            "A walking track that follows the coastline — beach esplanade, "
            "foreshore promenade, coastal track, harbour walk. Broader than "
            "Cliff Walks (which is specifically clifftops) and broader than "
            "Beaches (which is just the beach feature)."
        ),
        "positive_keywords": [
            r"\bcoastal walk\b",
            r"\bcoastal track\b",
            r"\bcoastal path\b",
            r"\bbeach walk\b",
            r"\besplanade\b",
            r"\bforeshore\b",
            r"\bharbour walk\b",
            r"\bharbor walk\b",
        ],
        "negative_signals": [],
    },
    {
        "name": "Conservation Projects",
        "definition": (
            "An active, ongoing conservation project that visitors can engage "
            "with — community trapping rounds, planting days, public "
            "volunteer programmes, iwi-led restoration. Past restorations with "
            "no current engagement belong in 'Restoration Sites' or "
            "'Ecological Restoration'."
        ),
        "positive_keywords": [
            r"\bconservation project\b",
            r"\bcommunity[- ]?led\b",
            r"\btrapping round\b",
            r"\bplanting day\b",
            r"\bvolunteer\b",
            r"\bcommunity planting\b",
            r"\bcommunity nursery\b",
            r"\briverkeeper\b",
            r"\briver care\b",
        ],
        "negative_signals": [
            "completed restoration",
        ],
    },
    {
        "name": "Cultural History",
        "definition": (
            "Broader-than-Māori cultural history — settler narratives, "
            "Chinese-NZ immigration, Dalmatian gumdiggers, Pacific diaspora, "
            "social-history movements. Use 'Māori History' for tangata whenua "
            "narratives, and 'Historic Sites' for buildings/ruins alone."
        ),
        "positive_keywords": [
            r"\bcultural history\b",
            r"\bsocial history\b",
            r"\bimmigration\b",
            r"\bimmigrant\b",
            r"\bsettler\b",
            r"\bdalmatian\b",
            r"\bchinese miner\b",
            r"\bpacific community\b",
            r"\bsamoan\b",
            r"\btongan\b",
            r"\boral history\b",
            r"\bintangible heritage\b",
        ],
        "negative_signals": [
            "māori",  # use 'Māori History'
            "iwi",
            "gold rush",  # use 'Gold Mining History'
        ],
    },
    {
        "name": "Cycle Trails",
        "definition": (
            "A dedicated cycling route — Ngā Haerenga / NZ Cycle Trail network "
            "(Otago Central Rail Trail, Hauraki Rail Trail), urban cycleways, "
            "mountain-bike park trails, gravel-bike loops. Multi-use tracks "
            "that permit cycling but aren't designed for it are weaker fits."
        ),
        "positive_keywords": [
            r"\bcycle trail\b",
            r"\bcycleway\b",
            r"\bbike trail\b",
            r"\bmountain bike\b",
            r"\bmtb\b",
            r"\brail trail\b",
            r"\bnz cycle trail\b",
            r"\bng[āa] haerenga\b",
            r"\bbike park\b",
            r"\bgravel ride\b",
        ],
        "negative_signals": [
            "no cycling",
            "walking only",
        ],
    },
    {
        "name": "DOC Campsites",
        "definition": (
            "A DOC-managed campsite — Basic, Standard, or Scenic classification. "
            "Holiday parks, commercial campgrounds, and freedom-camping spots "
            "do NOT qualify."
        ),
        "positive_keywords": [
            r"\bdoc campsite\b",
            r"\bdoc camp\b",
            r"\bconservation campsite\b",
            r"\bbasic camp\b",
            r"\bstandard camp\b",
            r"\bscenic campground\b",
            r"\bdoc camping\b",
        ],
        "negative_signals": [
            "holiday park",
            "commercial campground",
            "freedom camping",
        ],
    },
    {
        "name": "Dark Sky Places",
        "definition": (
            "Recognised dark-sky locations with negligible light pollution — "
            "IDA-designated Aoraki Mackenzie, Stewart Island Rakiura, Great "
            "Barrier / Aotea, plus generally remote inland places explicitly "
            "noted for night-sky viewing or astrophotography."
        ),
        "positive_keywords": [
            r"\bdark sky\b",
            r"\bdark[- ]?sky reserve\b",
            r"\bstargazing\b",
            r"\bmilky way\b",
            r"\bastrophotography\b",
            r"\bnight sky\b",
            r"\bida reserve\b",
            r"\bobservatory\b",
            r"\baoraki mackenzie\b",
            r"\bgreat barrier dark sky\b",
        ],
        "negative_signals": [],
    },
    {
        "name": "Ecological Restoration",
        "definition": (
            "A landscape that has undergone or is undergoing substantial "
            "ecological restoration — large-scale revegetation, wetland "
            "rebuild, mainland-island sanctuary establishment, dune "
            "rehabilitation. Distinct from 'Restoration Sites' which leans "
            "toward smaller, currently-active community projects, and from "
            "'Conservation Projects' (currently-active visitor engagement)."
        ),
        "positive_keywords": [
            r"\becological restoration\b",
            r"\brestoration\b",
            r"\brevegetation\b",
            r"\breplant(?:ed|ing)\b",
            r"\becosystem recovery\b",
            r"\bnative restoration\b",
            r"\bwetland restoration\b",
            r"\bdune restoration\b",
            r"\bregeneration\b",
        ],
        "negative_signals": [
            "heritage restoration",
            "building restoration",
        ],
    },
    {
        "name": "Exotic Forests",
        "definition": (
            "Non-native plantation forest — commercial pine, Douglas fir, "
            "redwood groves, eucalyptus stands, macrocarpa shelterbelts. Native "
            "forests (beech, kauri, podocarp, rainforest) all have their own "
            "tags."
        ),
        "positive_keywords": [
            r"\bpine forest\b",
            r"\bexotic forest\b",
            r"\bplantation\b",
            r"\bdouglas fir\b",
            r"\bredwood\b",
            r"\beucalyptus\b",
            r"\bmacrocarpa\b",
            r"\bmonterey pine\b",
            r"\bradiata\b",
            r"\bexotic species\b",
        ],
        "negative_signals": [
            "native forest",
            "podocarp",
            "beech",
            "kauri",
        ],
    },
    {
        "name": "Family Friendly",
        "definition": (
            "Suitable for children of varied ages — short distances, stroller- "
            "or buggy-friendly surfaces, low fall risk, playgrounds or hands-on "
            "interactive features. Alpine, exposed, or technical sites don't "
            "qualify even if children HAVE done them."
        ),
        "positive_keywords": [
            r"\bfamily friendly\b",
            r"\bfamilies\b",
            r"\bkid friendly\b",
            r"\bkids? love\b",
            r"\bplayground\b",
            r"\bsuitable for children\b",
            r"\bstroller\b",
            r"\bpram\b",
            r"\bpushchair\b",
            r"\beasy stroll\b",
        ],
        "negative_signals": [
            "exposed",
            "advanced",
            "alpine",
            "steep drop",
        ],
    },
    {
        "name": "Fishing",
        "definition": (
            "A notable fishing destination — named trout river/stream, surf-cast "
            "beach, harbour-fishing wharf, fly-fishing reach, named saltwater "
            "spot. Casual mention of 'good fishing' without specifics is weaker."
        ),
        "positive_keywords": [
            r"\bfishing\b",
            r"\bangler\b",
            r"\bangling\b",
            r"\btrout\b",
            r"\bsalmon\b",
            r"\bsurf casting\b",
            r"\bsurf[- ]?cast\b",
            r"\bfly fishing\b",
            r"\bfly[- ]?fish\b",
            r"\bsnapper\b",
            r"\bkahawai\b",
            r"\bgurnard\b",
            r"\bfish (?:charter|guide)\b",
        ],
        "negative_signals": [
            "marine reserve",  # likely no-take
            "no fishing",
        ],
    },
    {
        "name": "Forest Walks",
        "definition": (
            "A walking track through forested landscape — native bush, beech, "
            "kauri, podocarp, rainforest, or exotic plantation. Coastal walks "
            "with patches of forest don't qualify (those are Coastal Walks)."
        ),
        "positive_keywords": [
            r"\bforest walk\b",
            r"\bbush walk\b",
            r"\bforest track\b",
            r"\bthrough (?:native )?bush\b",
            r"\bunder the canopy\b",
            r"\bbeech forest walk\b",
            r"\brimu\b",
            r"\bpodocarp\b",
        ],
        "negative_signals": [
            "alpine",
            "coastal",
            "urban",
        ],
    },
    {
        "name": "Fossil Sites",
        "definition": (
            "Locations where fossils are visible in the rock, or where notable "
            "palaeontological finds have been made — ammonite beds, foraminiferal "
            "exposures, dinosaur bone discoveries, mokoia / South Island "
            "fossiliferous formations."
        ),
        "positive_keywords": [
            r"\bfossil\b",
            r"\bfossili[sz]ed\b",
            r"\bdinosaur\b",
            r"\bpalaeontolog\b",
            r"\bpaleontolog\b",
            r"\bammonite\b",
            r"\bforamin[i]?fera\b",
            r"\btrilobite\b",
            r"\bweathered exposure\b",
            r"\bpetrified\b",
        ],
        "negative_signals": [],
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
        "name": "Geological Sites",
        "definition": (
            "Notable geological features — folded sedimentary beds, fault "
            "lines/scarps, columnar basalt, named rock formations, schist "
            "exposures, ophiolite, named pluton outcrops. Generic 'rocky place' "
            "or 'big rock' don't qualify; there must be a named or describable "
            "geological feature."
        ),
        "positive_keywords": [
            r"\bgeology\b",
            r"\bgeological\b",
            r"\bfault\b",
            r"\bfault line\b",
            r"\bcolumnar\b",
            r"\bbasalt\b",
            r"\bschist\b",
            r"\bgreywacke\b",
            r"\bgranite\b",
            r"\bsedimentary\b",
            r"\bdolomite\b",
            r"\bpluton\b",
            r"\bophiolite\b",
            r"\bmineral\b",
            r"\bstrata\b",
        ],
        "negative_signals": [
            "just a mountain",
            "just cliffs",
        ],
    },
    {
        "name": "Glacial Lakes",
        "definition": (
            "Lakes formed or dammed by glacial action — turquoise moraine "
            "lakes, hanging-valley tarns, kettle lakes. Hooker, Tasman, Mueller "
            "Lake style. Distinct from generic 'Lakes' (any waterbody) and from "
            "'Glaciers' (the ice body itself)."
        ),
        "positive_keywords": [
            r"\bglacial lake\b",
            r"\bmoraine lake\b",
            r"\bturquoise lake\b",
            r"\bglacier[- ]?fed\b",
            r"\bblue lake\b",
            r"\balpine lake\b",
            r"\bhooker lake\b",
            r"\btasman lake\b",
            r"\bkettle lake\b",
            r"\btarn\b",
        ],
        "negative_signals": [
            "hydro lake",
            "artificial lake",
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
    # road, tramway, etc.) rolled into the 'Heritage Trails' definition below.
    {
        "name": "Gold Mining History",
        "definition": (
            "Specifically Otago / West Coast / Coromandel gold-rush era — "
            "goldfields, dredges, stamper batteries, water races, sluice "
            "channels, miners' huts, gold towns. Coal / silver / iron mining "
            "go in 'Mining History'."
        ),
        "positive_keywords": [
            r"\bgold mine\b",
            r"\bgold rush\b",
            r"\bgoldfield\b",
            r"\btailings\b",
            r"\bsluice\b",
            r"\bwater race\b",
            r"\bstamper battery\b",
            r"\bdredge\b",
            r"\bminers\b",
            r"\bchinese miner\b",
        ],
        "negative_signals": [
            "coal mine",
            "silver mine",
        ],
    },
    {
        "name": "Gravel Roads",
        "definition": (
            "Unsealed gravel / dirt road access to the place. Most 2WD cars "
            "manage it in dry conditions; expect dust, slower speeds, and "
            "possible degradation in wet. This tag is NOT a 4WD signal — that "
            "is the separate '4WD Recommended' tag. Replaces the old "
            "'4WD Access' tag which was over-applied to gravel-only places."
        ),
        "positive_keywords": [
            r"\bgravel road\b",
            r"\bunsealed road\b",
            r"\bdirt road\b",
            r"\bmetal road\b",
            r"\bgravel access\b",
            r"\bunsealed access\b",
            r"\bdusty road\b",
        ],
        "negative_signals": [
            "sealed road",
            "fully sealed",
            "4wd required",
            "4wd only",
        ],
    },
    {
        "name": "Great Walks",
        "definition": (
            "One of DOC's branded Great Walks specifically — Milford, Routeburn, "
            "Kepler, Abel Tasman Coast, Heaphy, Tongariro Northern Circuit, "
            "Lake Waikaremoana, Rakiura, Paparoa, Whanganui Journey, Hump "
            "Ridge. Generic 'great walk' phrasing for non-listed tracks does "
            "NOT qualify."
        ),
        "positive_keywords": [
            r"\bgreat walk\b",
            r"\bgreat walks\b",
            r"\bmilford track\b",
            r"\brouteburn track\b",
            r"\bkepler track\b",
            r"\babel tasman coast track\b",
            r"\bheaphy track\b",
            r"\btongariro northern circuit\b",
            r"\bpaparoa track\b",
            r"\brakiura track\b",
            r"\blake waikaremoana\b",
            r"\bhump ridge\b",
            r"\bwhanganui journey\b",
        ],
        "negative_signals": [],
    },
    {
        "name": "Heritage Precincts",
        "definition": (
            "A conserved historic streetscape or named heritage zone — restored "
            "townscapes, council-designated heritage areas, historic "
            "commercial precincts (Oamaru Victorian Precinct, Arrowtown, "
            "Akaroa). A single building doesn't qualify; the *precinct* must "
            "be the feature."
        ),
        "positive_keywords": [
            r"\bheritage precinct\b",
            r"\bheritage zone\b",
            r"\brestored streetscape\b",
            r"\bhistoric centre\b",
            r"\bhistoric town centre\b",
            r"\bconservation area\b",
            r"\boamaru victorian\b",
            r"\barrowtown\b",
        ],
        "negative_signals": [],
    },
    {
        "name": "Heritage Trails",
        "definition": (
            "A walking or driving trail with interpretive heritage content — "
            "gold-mining tramway, surveyors' route, old coach road, war trail, "
            "Cobb & Co route, interpretive signage along the route. Distinct "
            "from 'Historic Sites' (a discrete site, not a trail) and "
            "'Gold Mining History' (the era/activity, not the route format)."
        ),
        "positive_keywords": [
            r"\bheritage trail\b",
            r"\bhistorical trail\b",
            r"\bhistoric trail\b",
            r"\binterpretive walk\b",
            r"\binterpretive signage\b",
            r"\bcoach road\b",
            r"\bold coach\b",
            r"\bsurveyor[s']? route\b",
            r"\bpack track\b",
            r"\btramway\b",
            r"\bwagon road\b",
            r"\bcobb (?:and|&) co\b",
        ],
        "negative_signals": [],
    },
    {
        "name": "Hidden Gems",
        "definition": (
            "UMBRELLA tag for less-visited places in any of four senses — "
            "(1) under-promoted ('locals' secret', 'overlooked', 'underrated'), "
            "(2) out-of-the-way (end of a gravel road, walk-in-only, "
            "off-the-beaten-track), (3) peaceful and low-traffic (secluded "
            "bays, restful tracks, tranquil spots), or (4) geographically "
            "remote (East Cape, Catlins ends, far Fiordland, Stewart Island). "
            "Genuinely popular / iconic places do NOT qualify even if the "
            "prose uses 'hidden' loosely.\n\n"
            "Consolidates four previously-separate tags as of 2026-06-24 — "
            "'Hidden Gems', 'Off The Beaten Track', 'Quiet Spots', and "
            "'Remote Locations'. Sanity may still carry the other three tag "
            "documents (until they're explicitly retired) but our LLM "
            "re-tag pass will only ever propose 'Hidden Gems'. If Douglas "
            "reverses this consolidation later, see "
            "directives/tag_consolidations_2026-06-24.md for the original "
            "individual definitions and how to restore them."
        ),
        "positive_keywords": [
            # framing-led (original Hidden Gems)
            r"\bhidden gem\b",
            r"\bhidden\b",
            r"\boverlooked\b",
            r"\bundiscovered\b",
            r"\bsecret spot\b",
            r"\blocal[s']? secret\b",
            r"\bnot many people\b",
            r"\bunderrated\b",
            r"\blesser[- ]?known\b",
            # distance-led (original Off The Beaten Track)
            r"\boff the beaten track\b",
            r"\boff the beaten path\b",
            r"\bless visited\b",
            r"\bfewer people\b",
            r"\bremote feel\b",
            r"\bget away from\b",
            r"\bquieter alternative\b",
            r"\bend of the road\b",
            # atmosphere-led (original Quiet Spots)
            r"\bquiet\b",
            r"\bpeaceful\b",
            r"\bsecluded\b",
            r"\btranquil\b",
            r"\brestful\b",
            r"\bcalm\b",
            r"\bgentle\b",
            r"\bunwind\b",
            # isolation-led (original Remote Locations)
            r"\bremote\b",
            r"\bisolated\b",
            r"\bfar from\b",
            r"\bdistant\b",
            r"\bmiles from\b",
            r"\bno (?:cell )?signal\b",
            r"\bwilderness\b",
            r"\blast outpost\b",
        ],
        "negative_signals": [
            "famous",
            "popular",
            "well known",
            "iconic",
            "tourist hot spot",
            "crowded",
            "busy",
        ],
    },
    {
        "name": "High Country",
        "definition": (
            "South Island high-altitude tussock / sub-alpine landscape — "
            "Mackenzie Basin, Otago high country, Canterbury foothills run-back "
            "country, named stations (Glentanner, Erewhon, Lilybank). Not "
            "applicable to alpine peaks themselves (those are Mountains) or to "
            "North Island tussock zones (which are usually smaller-scale)."
        ),
        "positive_keywords": [
            r"\bhigh country\b",
            r"\btussock\b",
            r"\balpine grassland\b",
            r"\bmackenzie\b",
            r"\bsub[- ]?alpine\b",
            r"\bmontane\b",
            r"\bhigh country station\b",
            r"\brun[- ]?back\b",
            r"\bglentanner\b",
            r"\bmolesworth\b",
        ],
        "negative_signals": [
            "coastal",
            "lowland",
            "rainforest",
        ],
    },
    {
        "name": "Hikes",
        "definition": (
            "A moderate one-day walk — longer or more demanding than a 'Short "
            "Walk' but completable as a return day trip. Day hikes up named "
            "peaks, single-day ridge walks, longer forest tracks. Sits between "
            "'Short Walks' and 'Tramps' on the difficulty scale."
        ),
        "positive_keywords": [
            r"\bhike\b",
            r"\bhiking\b",
            r"\bday hike\b",
            r"\bfull[- ]?day walk\b",
            r"\bmoderate walk\b",
            r"\breturn day\b",
            r"\bhalf[- ]?day to (?:a )?full day\b",
        ],
        "negative_signals": [
            "short walk",       # use 'Short Walks'
            "multi-day",        # use 'Tramps' or 'Multi-Day Walks'
            "easy stroll",
        ],
    },
    {
        "name": "Historic Sites",
        "definition": (
            "Discrete historic sites — buildings, ruins, restored mills, "
            "industrial heritage, named historic homesteads, war fortifications. "
            "If the article is about a trail with interpretive content along "
            "the way, use 'Heritage Trails'. If a named district, use "
            "'Heritage Precincts'."
        ),
        "positive_keywords": [
            r"\bhistoric\b",
            r"\bhistorical\b",
            r"\bheritage building\b",
            r"\bruins\b",
            r"\brestored\b",
            r"\boriginal\b",
            r"\b19th century\b",
            r"\b1800s\b",
            r"\bvictorian\b",
            r"\bcolonial\b",
            r"\bpioneer\b",
            r"\bnzhpt\b",
            r"\bheritage new zealand\b",
        ],
        "negative_signals": [],
    },
    {
        "name": "Islands",
        "definition": (
            "An island or islands worth visiting — offshore islands, harbour "
            "islands, lake islands. Must be a discrete landmass surrounded by "
            "water as the named destination. 'Island' in a place name alone "
            "doesn't qualify (e.g., 'Kahurangi National Park' contains "
            "islands, but the park itself isn't this tag)."
        ),
        "positive_keywords": [
            r"\bisland\b",
            r"\bisle\b",
            r"\bmotu\b",
            r"\boffshore island\b",
            r"\bharbour island\b",
            r"\bharbor island\b",
            r"\bmainland island\b",
            r"\bferry to\b",
        ],
        "negative_signals": [],
    },
    {
        "name": "Kauri Forests",
        "definition": (
            "Forests with significant living kauri (Agathis australis) — "
            "Waipoua, Trounson, Puketi, Coromandel kauri groves, named giants "
            "like Tāne Mahuta. Kauri-dieback biosecurity is almost always "
            "relevant and should also get the 'Biosecurity Access' tag."
        ),
        "positive_keywords": [
            r"\bkauri\b",
            r"\bagathis australis\b",
            r"\bkauri forest\b",
            r"\bkauri grove\b",
            r"\bt[āa]ne mahuta\b",
            r"\bwaipoua\b",
            r"\btrounson\b",
            r"\bpuketi\b",
            r"\bkauri tree\b",
        ],
        "negative_signals": [],
    },
    {
        "name": "Lake and River Walks",
        "definition": (
            "Walking tracks alongside lakes or rivers — lake-edge promenades, "
            "river-bank tracks, gorge walks following a river. Distinct from "
            "'Forest Walks' (forest-focused), 'Coastal Walks' (sea-focused), "
            "and 'Cliff Walks'."
        ),
        "positive_keywords": [
            r"\blakeside walk\b",
            r"\blake walk\b",
            r"\briver walk\b",
            r"\briverside\b",
            r"\briverbank\b",
            r"\blake[- ]?edge\b",
            r"\bgorge walk\b",
            r"\bwaterside walk\b",
        ],
        "negative_signals": [],
    },
    {
        "name": "Lakes",
        "definition": (
            "A lake as the named destination — natural, hydro, glacial, "
            "alpine. For specifically glacier-fed turquoise lakes use the "
            "'Glacial Lakes' tag. For lake-edge walks use 'Lake and River "
            "Walks'."
        ),
        "positive_keywords": [
            r"\blake\b",
            r"\blakes\b",
            r"\bfreshwater lake\b",
            r"\bhydro lake\b",
            r"\btarn\b",
            r"\bcrater lake\b",
            r"\boxbow\b",
        ],
        "negative_signals": [],
    },
    {
        "name": "Local Legends & Myths",
        "definition": (
            "Sites carrying significant pūrākau / oral tradition — taniwha "
            "stories, named atua / tūpuna events, locality-specific legends, "
            "named ancestor narratives. Often (but not always) Māori in origin; "
            "settler folk-tales also qualify if substantively documented."
        ),
        "positive_keywords": [
            r"\blegend\b",
            r"\bmyth\b",
            r"\btaniwha\b",
            r"\batua\b",
            r"\bdemigod\b",
            r"\bp[ūu]r[āa]kau\b",
            r"\boral tradition\b",
            r"\bnamed after\b",
            r"\bthe story goes\b",
            r"\baccording to\b",
            r"\btradition\b",
        ],
        "negative_signals": [],
    },
    {
        "name": "Lookouts",
        "definition": (
            "A designated viewpoint with significant views — built lookout "
            "platforms, named viewpoints, sweeping vistas at the end of a "
            "short walk, panoramic-view roadside stops. Generic 'great view "
            "from the top' on a longer walk doesn't qualify by itself."
        ),
        "positive_keywords": [
            r"\blookout\b",
            r"\bviewpoint\b",
            r"\bscenic lookout\b",
            r"\bpanoramic\b",
            r"\bvista\b",
            r"\bobservation deck\b",
            r"\bviewing platform\b",
            r"\bscenic outlook\b",
            r"\bvantage point\b",
        ],
        "negative_signals": [],
    },
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
        "name": "Marine Reserves",
        "definition": (
            "Legally gazetted Marine Reserves — Cape Rodney–Okakari Point "
            "(Leigh / Goat Island), Tāwharanui, Tonga Island (Abel Tasman), "
            "Tapuwae o Rongokako, etc. No-take fishing restrictions apply. "
            "Marine parks and marine-mammal sanctuaries do NOT qualify unless "
            "they are also reserves."
        ),
        "positive_keywords": [
            r"\bmarine reserve\b",
            r"\bmarine protected\b",
            r"\bno[- ]?take\b",
            r"\bmarine sanctuary\b",
            r"\bmarine park\b",  # weaker
            r"\bcape rodney\b",
            r"\bgoat island reserve\b",
        ],
        "negative_signals": [
            "no protection",
        ],
    },
    {
        "name": "Memorials",
        "definition": (
            "War memorials, disaster memorials, formal commemorative monuments. "
            "Often ANZAC-related cenotaphs but also mining / shipping / "
            "earthquake / Tangiwai-style commemorations. Generic plaques "
            "naming a place after a person don't qualify; the *memorial* "
            "itself must be the destination."
        ),
        "positive_keywords": [
            r"\bmemorial\b",
            r"\bcenotaph\b",
            r"\bmonument\b",
            r"\bwar memorial\b",
            r"\banzac\b",
            r"\blest we forget\b",
            r"\bdedicated to\b",
            r"\bin memory of\b",
            r"\bcommemorat\b",
        ],
        "negative_signals": [
            "small plaque",
        ],
    },
    {
        "name": "Mining History",
        "definition": (
            "Non-gold mining history — coal mines (West Coast, Brunner, "
            "Pike River), silver / copper / iron extraction, antimony, "
            "ironsand. Old gold-mining sites go in 'Gold Mining History'."
        ),
        "positive_keywords": [
            r"\bcoal mine\b",
            r"\bsilver mine\b",
            r"\bcopper mine\b",
            r"\biron mine\b",
            r"\bironsand\b",
            r"\bantimony\b",
            r"\bsmelter\b",
            r"\bore\b",
            r"\bpit\b",
            r"\bbrunner\b",
            r"\bdenniston\b",
        ],
        "negative_signals": [
            "gold rush",
            "goldfield",
        ],
    },
    {
        "name": "Mountains",
        "definition": (
            "Named peaks or mountains as the primary feature — viewed from "
            "below, climbed, or used as the orientation point for the article. "
            "Tongariro, Taranaki, Aoraki, Hikurangi, Tarawera. Volcanic cones "
            "should also get 'Volcanos'. Climbed routes that require "
            "mountaineering also get 'Alpine Routes'."
        ),
        "positive_keywords": [
            r"\bmountain\b",
            r"\bmt\b",
            r"\bmount\b",
            r"\bpeak\b",
            r"\bsummit\b",
            r"\bmaunga\b",
            r"\baoraki\b",
            r"\btaranaki\b",
            r"\bruapehu\b",
            r"\btongariro\b",
            r"\bhikurangi\b",
            r"\btarawera\b",
            r"\bmauao\b",
        ],
        "negative_signals": [],
    },
    {
        "name": "Multi-Day Walks",
        "definition": (
            "A walking track taking 2+ days — DOC Great Walks plus other "
            "multi-day tramps (Cape Brett, Pouakai Circuit, Travers-Sabine, "
            "Holdsworth-Jumbo). Use 'Great Walks' specifically for DOC-branded "
            "ones."
        ),
        "positive_keywords": [
            r"\bmulti[- ]?day\b",
            r"\btwo[- ]?day\b",
            r"\bthree[- ]?day\b",
            r"\bfour[- ]?day\b",
            r"\bovernight tramp\b",
            r"\bhut to hut\b",
            r"\bcircuit\b",
            r"\b[0-9]+ nights?\b",
            r"\b[0-9]+ days walking\b",
        ],
        "negative_signals": [
            "half day",
            "single day",
            "return walk",
            "day walk",
        ],
    },
    {
        "name": "Museums",
        "definition": (
            "Indoor curated museum collections — natural history, social "
            "history, transport, maritime, military, regional. Te Papa, Otago "
            "Museum, MOTAT, Toitū. Art-only spaces are 'Art Galleries'."
        ),
        "positive_keywords": [
            r"\bmuseum\b",
            r"\bexhibits\b",
            r"\bcollection\b",
            r"\bte papa\b",
            r"\botago museum\b",
            r"\bmotat\b",
            r"\bmaritime museum\b",
            r"\btransport museum\b",
            r"\bwar museum\b",
            r"\btoit[ūu]\b",
        ],
        "negative_signals": [],
    },
    {
        "name": "National Parks",
        "definition": (
            "DOC-designated National Parks — Fiordland, Tongariro, Aoraki / "
            "Mount Cook, Kahurangi, Westland Tai Poutini, Abel Tasman, Mount "
            "Aspiring, Egmont / Taranaki Mounga, Whanganui, Te Urewera, "
            "Paparoa, Nelson Lakes, Arthur's Pass, Rakiura. Forest parks and "
            "marine parks don't qualify (those are 'Regional Parks' or "
            "'Marine Reserves' respectively)."
        ),
        "positive_keywords": [
            r"\bnational park\b",
            r"\bfiordland\b",
            r"\btongariro np\b",
            r"\baoraki\b",
            r"\bkahurangi\b",
            r"\bwestland tai poutini\b",
            r"\babel tasman\b",
            r"\bmount aspiring\b",
            r"\begmont\b",
            r"\btaranaki mounga\b",
            r"\bte urewera\b",
            r"\bpaparoa np\b",
            r"\bnelson lakes\b",
            r"\barthur's pass\b",
        ],
        "negative_signals": [
            "forest park",
            "regional park",
        ],
    },
    {
        "name": "Natural Arches",
        "definition": (
            "Naturally-formed rock arches — sea arches eroded by waves "
            "(Cathedral Cove, Punakaiki area), inland weathered arches (Castle "
            "Hill, Elephant Rocks). Built bridges or stone arches in human "
            "structures do NOT qualify."
        ),
        "positive_keywords": [
            r"\bnatural arch\b",
            r"\brock arch\b",
            r"\bsea arch\b",
            r"\barchway\b",
            r"\beroded arch\b",
            r"\barched rock\b",
            r"\bcathedral cove\b",
            r"\bblowholes (?:and|&) arches\b",
        ],
        "negative_signals": [
            "stone bridge",
            "built arch",
        ],
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
    # 'Off The Beaten Track' definition consolidated into 'Hidden Gems'
    # umbrella tag (2026-06-24). LLM re-tag will not propose this tag; the
    # Sanity tag document may still exist. See directives/
    # tag_consolidations_2026-06-24.md for the original definition + how to
    # restore if Douglas reverses the call.
    {
        "name": "Photography Spots",
        "definition": (
            "Explicitly photogenic / iconic photography locations — sunrise / "
            "sunset positions, named viewpoints often shot, dramatic backdrops "
            "for portraits, Instagram-recognised sites. Generic 'scenic spots' "
            "don't qualify without specific photography framing."
        ),
        "positive_keywords": [
            r"\bphotograph(?:ic|y)\b",
            r"\bphotogenic\b",
            r"\biconic shot\b",
            r"\biconic view\b",
            r"\binstagram\b",
            r"\bgolden hour\b",
            r"\bphotographers? love\b",
            r"\bmost[- ]?photographed\b",
        ],
        "negative_signals": [],
    },
    {
        "name": "Podocarp Forests",
        "definition": (
            "Native NZ podocarp species are the named feature — rimu, tōtara, "
            "kahikatea (white pine), mātai, miro, halocarpus. Often wet "
            "lowland or river-flat forest. Beech and kauri have their own tags."
        ),
        "positive_keywords": [
            r"\bpodocarp\b",
            r"\brimu\b",
            r"\bt[ōo]tara\b",
            r"\bkahikatea\b",
            r"\bm[āa]tai\b",
            r"\bmiro\b",
            r"\bhalocarpus\b",
            r"\bdacrydium\b",
            r"\bdracophyllum\b",
        ],
        "negative_signals": [
            "beech forest",
            "kauri",
        ],
    },
    {
        "name": "Public Art and Sculpture",
        "definition": (
            "Outdoor public art — sculpture trails, named installations, "
            "murals, civic artworks, named artist commissions. Indoor galleries "
            "are 'Art Galleries'."
        ),
        "positive_keywords": [
            r"\bsculpture\b",
            r"\bpublic art\b",
            r"\bmural\b",
            r"\bart trail\b",
            r"\binstallation\b",
            r"\bartwork\b",
            r"\bsculpture trail\b",
            r"\bsculpture park\b",
            r"\bgilbert van reenen\b",  # weak but possible
        ],
        "negative_signals": [
            "indoor gallery",
        ],
    },
    # 'Quiet Spots' definition consolidated into 'Hidden Gems' umbrella tag
    # (2026-06-24). See directives/tag_consolidations_2026-06-24.md.
    {
        "name": "Rainforest",
        "definition": (
            "Temperate rainforest — wet podocarp / broadleaf forest with "
            "abundant epiphytes, mosses, tree ferns. Mostly West Coast, "
            "Fiordland, Westland. Distinct from dry beech forest or alpine "
            "scrub."
        ),
        "positive_keywords": [
            r"\brainforest\b",
            r"\btemperate rainforest\b",
            r"\bwest coast forest\b",
            r"\bfiordland forest\b",
            r"\btreefern\b",
            r"\btree fern\b",
            r"\bponga\b",
            r"\bepiphyte\b",
            r"\bmossy\b",
            r"\bdripping with moss\b",
        ],
        "negative_signals": [
            "dry beech forest",
            "alpine scrub",
        ],
    },
    {
        "name": "Regional Parks",
        "definition": (
            "Local-authority-managed regional parks (Auckland Regional Parks, "
            "Greater Wellington Regional Parks, Christchurch metro reserves). "
            "DOC-managed National Parks have their own tag; small town/city "
            "parks are 'Town Parks' / 'City Parks'."
        ),
        "positive_keywords": [
            r"\bregional park\b",
            r"\bregional parks\b",
            r"\bcouncil reserve\b",
            r"\bregional reserve\b",
            r"\bauckland council park\b",
            r"\bregional council\b",
        ],
        "negative_signals": [
            "national park",
            "city park",
            "town park",
        ],
    },
    # 'Remote Locations' definition consolidated into 'Hidden Gems' umbrella
    # tag (2026-06-24). See directives/tag_consolidations_2026-06-24.md.
    {
        "name": "Remote Road",
        "definition": (
            "A specifically scenic, remote driving route worth doing for its "
            "own sake — long unsealed roads to back-country, named scenic "
            "isolated drives (Skippers Canyon, Macetown, parts of the East "
            "Cape SH35). Currently zero pages tagged in Sanity — may overlap "
            "with 'Scenic Drives' + 'Gravel Roads'; Douglas may retire."
        ),
        "positive_keywords": [
            r"\bremote road\b",
            r"\bisolated road\b",
            r"\bend of the road\b",
            r"\bback[- ]?country road\b",
            r"\bremote drive\b",
            r"\bskippers canyon\b",
            r"\bmacetown\b",
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
        "name": "Rivers",
        "definition": (
            "A named river as the destination — swimming holes, viewing "
            "spots, gorges, river-mouth estuaries, awa. Streams and brooks "
            "are usually too small. River-bank walks are 'Lake and River Walks'."
        ),
        "positive_keywords": [
            r"\briver\b",
            r"\briverbank\b",
            r"\bgorge\b",
            r"\briver valley\b",
            r"\bswimming hole\b",
            r"\bawa\b",
            r"\bbraided river\b",
            r"\bestuary\b",
            r"\bdelta\b",
        ],
        "negative_signals": [
            "stream",  # smaller
            "brook",
        ],
    },
    {
        "name": "Scenic Drives",
        "definition": (
            "Drives notable for their scenery — named scenic routes, mountain "
            "passes, coast roads, Lindis Pass, Crown Range, Twin Coast "
            "Discovery, Forgotten World Highway. Generic roads aren't this "
            "tag."
        ),
        "positive_keywords": [
            r"\bscenic drive\b",
            r"\bscenic route\b",
            r"\bpicturesque road\b",
            r"\bmountain pass\b",
            r"\bcoast road\b",
            r"\bcrown range\b",
            r"\blindis pass\b",
            r"\btwin coast\b",
            r"\bforgotten world\b",
            r"\broad trip\b",
        ],
        "negative_signals": [],
    },
    {
        "name": "Scenic Loops",
        "definition": (
            "A walk or drive that returns to its starting point as a loop / "
            "circuit — circular tracks, day-loop drives, named circuit walks. "
            "Out-and-back walks where you retrace your steps do NOT qualify."
        ),
        "positive_keywords": [
            r"\bscenic loop\b",
            r"\bloop walk\b",
            r"\bloop drive\b",
            r"\bcircular\b",
            r"\bfull circuit\b",
            r"\breturns to (?:the )?start\b",
            r"\bcircuit\b",
        ],
        "negative_signals": [
            "out and back",
            "one way",
            "retrace",
        ],
    },
    {
        "name": "Scenic Reserves",
        "definition": (
            "DOC- or council-gazetted Scenic Reserve — a legally protected area "
            "set aside for its scenic, scientific, or natural value under the "
            "Reserves Act. Distinct from National Parks (larger, DOC-only) and "
            "Regional Parks (local-authority managed for recreation). Picnic "
            "areas / day-use spots are NOT the same concept and should not "
            "trigger this tag on their own."
        ),
        "positive_keywords": [
            r"\bscenic reserve\b",
            r"\bscenic recreation reserve\b",
            r"\bdoc reserve\b",
            r"\bscenic protected\b",
            r"\breserves act\b",
            r"\bgazetted reserve\b",
        ],
        "negative_signals": [
            "picnic area",  # picnic ≠ scenic reserve
            "picnic spot",
            "regional park",
            "national park",
        ],
    },
    {
        "name": "Sea Caves",
        "definition": (
            "Coastal caves carved by wave action — Cathedral Cove style "
            "wave-cut openings, sea-level cave passages, named coastal caves. "
            "Inland (limestone, karst, lava-tube) caves go in the separate "
            "'Caves' tag. Tide-sensitive — only safely accessible at low tide "
            "in most cases."
        ),
        "positive_keywords": [
            r"\bsea cave\b",
            r"\bsea[- ]?cut cave\b",
            r"\bmarine cave\b",
            r"\bcoastal cave\b",
            r"\bcathedral cove\b",
            r"\bwave[- ]?cut\b",
        ],
        "negative_signals": [
            "inland cave",
            "limestone cave",
            "karst",
        ],
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
        "name": "Short Walks",
        "definition": (
            "Easy walks under ~1 hour return — kid-friendly, often paved or "
            "well-formed, short loops or out-and-back from a car park. Use "
            "'Hikes' for moderate day-length walks and 'Boardwalks' for built "
            "wooden walkways specifically."
        ),
        "positive_keywords": [
            r"\bshort walk\b",
            r"\beasy walk\b",
            r"\beasy stroll\b",
            r"\b30 minute walk\b",
            r"\b10 minute walk\b",
            r"\b15 minute walk\b",
            r"\b20 minute walk\b",
            r"\bgentle walk\b",
            r"\bunder an hour\b",
            r"\bquick walk\b",
        ],
        "negative_signals": [
            "full day",
            "multi-day",
            "demanding",
        ],
    },
    {
        "name": "Sunrise Spots",
        "definition": (
            "Locations explicitly framed as sunrise-viewing spots — east-facing "
            "coast, named dawn lookouts, places to watch first light. East "
            "Cape lighthouse, Cape Reinga, Mt Hobson. Generic 'morning views' "
            "aren't enough."
        ),
        "positive_keywords": [
            r"\bsunrise\b",
            r"\bdawn\b",
            r"\bfirst light\b",
            r"\beast[- ]?facing\b",
            r"\bmorning glow\b",
            r"\bsee the sun rise\b",
            r"\bfirst to see the sun\b",
            r"\bdawn chorus\b",
        ],
        "negative_signals": [
            "sunset",
            "west facing",
        ],
    },
    {
        "name": "Sunset Spots",
        "definition": (
            "Locations explicitly framed as sunset-viewing spots — west-facing "
            "beaches, named dusk lookouts, golden-hour terraces. Bethells, "
            "Castlepoint, Cape Foulwind west coast spots. Generic 'evening "
            "views' aren't enough."
        ),
        "positive_keywords": [
            r"\bsunset\b",
            r"\bdusk\b",
            r"\bevening\b",
            r"\bwest[- ]?facing\b",
            r"\bgolden hour\b",
            r"\bsee the sun set\b",
            r"\blast light\b",
            r"\bsunsets over\b",
        ],
        "negative_signals": [
            "sunrise",
            "east facing",
        ],
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
        "name": "Swimming Spots",
        "definition": (
            "Places explicitly recommended for swimming — sheltered swimming "
            "beaches, river swimming holes, calm-water bays, named "
            "swimming-spot signs. Surf beaches usually go to 'Surfing' "
            "instead; rip-prone or dangerous coasts don't qualify."
        ),
        "positive_keywords": [
            r"\bswimming\b",
            r"\bswim\b",
            r"\bswimming hole\b",
            r"\bsafe (?:to|for) swim\b",
            r"\bcalm water\b",
            r"\bswimmable\b",
            r"\bswimming beach\b",
            r"\bdiving platform\b",
            r"\bswim spot\b",
        ],
        "negative_signals": [
            "dangerous current",
            "rip",
            "undertow",
            "not safe for swimming",
        ],
    },
    {
        "name": "Te Araroa Trail",
        "definition": (
            "The place is on or connects with Te Araroa — NZ's long-distance "
            "trail running from Cape Reinga to Bluff. Use specifically when "
            "the article mentions TA / Te Araroa context, not just any "
            "long-walk."
        ),
        "positive_keywords": [
            r"\bte araroa\b",
            r"\bte araroa trail\b",
            r"\bta trail\b",
            r"\bthe ta\b",
            r"\blong pathway\b",
            r"\bcape reinga to bluff\b",
            r"\bend[- ]?to[- ]?end\b",
            r"\bthru[- ]?hik\b",
        ],
        "negative_signals": [],
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
    {
        "name": "Tramps",
        "definition": (
            "NZ-specific multi-day or hard-day back-country walks beyond "
            "casual hikes — Pouakai Circuit, Travers-Sabine, Cape Brett, "
            "Mavora Lakes circuit. Use 'Great Walks' for the DOC-branded "
            "list and 'Multi-Day Walks' for general multi-night tracks. "
            "'Tramps' is the rougher, hut-to-hut, often river-crossing "
            "back-country flavour."
        ),
        "positive_keywords": [
            r"\btramp\b",
            r"\btramping\b",
            r"\bbackcountry\b",
            r"\bhut to hut\b",
            r"\balpine pass\b",
            r"\brugged\b",
            r"\bbushbash\b",
            r"\boff[- ]?track\b",
        ],
        "negative_signals": [
            "short walk",
            "day hike",
            "easy stroll",
        ],
    },
    {
        "name": "Urban Walks",
        "definition": (
            "Walks through built urban environments — waterfront promenades, "
            "city walks, harbour walks, named streetscape walks. Auckland "
            "Waterfront, Wellington Waterfront, Christchurch CBD loop. "
            "Distinct from 'City Parks' (which is the parks themselves)."
        ),
        "positive_keywords": [
            r"\burban walk\b",
            r"\bcity walk\b",
            r"\bwaterfront walk\b",
            r"\bharbour walk\b",
            r"\bharbor walk\b",
            r"\btown walk\b",
            r"\bstreetscape\b",
            r"\bcbd loop\b",
        ],
        "negative_signals": [
            "bush",
            "alpine",
            "remote",
        ],
    },
    {
        "name": "Volcanos",
        "definition": (
            "Volcanic features — cones, calderas, crater lakes, lava fields, "
            "geothermal vents, recent eruption sites. Auckland volcanic field, "
            "Tongariro cones, Tarawera, Whakaari/White Island, Rangitoto. "
            "Often overlaps with 'Mountains' for cone-shaped volcanos."
        ),
        "positive_keywords": [
            r"\bvolcano\b",
            r"\bvolcanic\b",
            r"\bcrater\b",
            r"\bcaldera\b",
            r"\bcone\b",
            r"\blava\b",
            r"\beruption\b",
            r"\bgeothermal\b",
            r"\bfumarole\b",
            r"\bash field\b",
            r"\bwhakaari\b",
            r"\brangitoto\b",
        ],
        "negative_signals": [],
    },
    {
        "name": "Waterfalls",
        "definition": (
            "Notable waterfalls of any size — single drops, multi-tier "
            "cascades, plunge pools, ribbon falls. Sutherland, Bridal Veil, "
            "Whangarei, Bowen, Stirling, Wairere etc. Generic 'small "
            "cascades along the track' don't qualify by themselves; the "
            "waterfall should be a destination."
        ),
        "positive_keywords": [
            r"\bwaterfall\b",
            r"\bfalls\b",
            r"\bcascade\b",
            r"\bplunge pool\b",
            r"\bribbon falls\b",
            r"\bfern falls\b",
            r"\bsutherland\b",
            r"\bbridal veil\b",
            r"\bbowen falls\b",
            r"\bstirling falls\b",
        ],
        "negative_signals": [],
    },
    {
        "name": "Wetlands",
        "definition": (
            "Marshes, swamps, peat bogs, lagoons, estuaries, intertidal "
            "mudflats — major bird-feeding habitat. Often Ramsar-listed sites "
            "(Whangamarino, Awarua, Farewell Spit, Kaipara). Distinct from "
            "'Lakes' (open water) and 'Rivers' (flowing)."
        ),
        "positive_keywords": [
            r"\bwetland\b",
            r"\bswamp\b",
            r"\bmarsh\b",
            r"\blagoon\b",
            r"\bestuary\b",
            r"\bbog\b",
            r"\bpeat bog\b",
            r"\bmudflat\b",
            r"\bintertidal\b",
            r"\bramsar\b",
            r"\bharakeke\b",
        ],
        "negative_signals": [],
    },
    {
        "name": "Wildlife Encounters",
        "definition": (
            "Places explicitly noted for wildlife viewing — dolphin tours, "
            "penguin colonies, fur seal haul-outs, named bird-watching sites, "
            "albatross colonies. Managed bird sanctuaries with active "
            "predator control go in 'Bird Sanctuaries' too. Generic 'might "
            "see birds' doesn't qualify by itself."
        ),
        "positive_keywords": [
            r"\bdolphin\b",
            r"\bwhale\b",
            r"\bpenguin\b",
            r"\bseal\b",
            r"\bsea lion\b",
            r"\bfur seal\b",
            r"\balbatross\b",
            r"\bgannet\b",
            r"\bkea\b",
            r"\bkiwi\b",
            r"\bk[ōo]k[āa]ko\b",
            r"\bt[ūu][īi]\b",
            r"\bbellbird\b",
            r"\bwildlife encounter\b",
            r"\bwildlife viewing\b",
        ],
        "negative_signals": [],
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


TAG_NAMES: list[str] = [t["name"] for t in TAG_DEFINITIONS]
# Backwards-compat alias from the old 15-tag pass — kept so nothing imports break.
TAG_NAMES_15 = TAG_NAMES


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
