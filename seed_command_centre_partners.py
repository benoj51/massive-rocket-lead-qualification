"""
Seed the Partners CRM with the Braze + Hightouch contacts referenced in
the Massive Rocket Command Centre context.

v1.0.0h: full roster — every name Ben pulled from the latest org charts
goes in here, with reporting lines (`reports_to_id`) preserved wherever
the source material was explicit, and email addresses inferred for the
gaps the user flagged. Inferred emails are tagged `email_inferred` so
the AE can audit/correct them later without re-typing the whole roster.

MR-priority contacts (top of mind for Ben — see his profile memory) get
the `mr_priority` tag + a tighter `cadence_days` so they surface in the
overdue queue first.

Run with:
    python3 seed_command_centre_partners.py
    APOLLO_USE_FIXTURES=1 python3 seed_command_centre_partners.py  # test-safe

Idempotent — re-runs upsert by stable id rather than duplicating rows.

Sources:
- Braze AMER/EMEA org charts (May 2026, Ben's working notes).
- Braze Partner org touchpoints (Glenn Bonforte + co-sell circle).
- Hightouch NA Sales org (May 12 2026 update — emails TBD, all
  inferred against the standard firstname.lastname@hightouch.com).

Hierarchy notes:
- Where the source said "reports directly to X (no SD layer)", the
  contact gets reports_to_id = X.
- Partner Success (Glenn) and Sales (Marina, etc.) sit in different
  functions and don't share a chain — siblings at the partner-root.
- The five "confirm against new org" legacy/cross-team folks
  (Imi de Daranyi, Rod Aimes, Abigail Tucker, Jase Buckley, the
  CSM/GSA bench) are seeded with reports_to_id=None and a `confirm_org`
  tag so the AE knows to verify before relying on them.

Email pattern: firstname.lastname@braze.com for Braze,
firstname.lastname@hightouch.com for Hightouch. Explicit exceptions
(e.androulaki, nader, kiley, etc.) override the pattern. Inferred
emails get the `email_inferred` tag so they're auditable.
"""
from __future__ import annotations

import re
import sys
from typing import Any

import partner_contacts_store
import partners_store


# ---------------------------------------------------------------------------
# Partner records
# ---------------------------------------------------------------------------

BRAZE_PARTNER = {
    "name": "Braze",
    "type": "Technology partner",
    "url": "braze.com",
    "owner": "Ben Ojuolape",
    "description": "Customer engagement platform — primary CEP partner for "
                    "MR's Retention + Migration plays.",
}

HIGHTOUCH_PARTNER = {
    "name": "Hightouch",
    "type": "Technology partner",
    "url": "hightouch.com",
    "owner": "Ben Ojuolape",
    "description": "Reverse-ETL / Composable CDP partner. Pairs with Braze "
                    "for Retention deals where the warehouse is the source "
                    "of truth.",
}


# ---------------------------------------------------------------------------
# Location → MR region + country normaliser
# ---------------------------------------------------------------------------

# Map every US state / metro mentioned in the roster to its MR region.
# Anything not in this map is passed through as-is to `country` and
# region left empty (so we never silently mis-tag a row).
_US_EAST_COAST = {
    "NYC", "New York", "New Jersey", "Connecticut", "Massachusetts",
    "New Hampshire", "Maine", "Rhode Island", "Vermont", "Pennsylvania",
    "Florida", "Georgia", "South Carolina", "North Carolina", "Virginia",
    "Maryland", "DC", "Washington DC", "Delaware",
}
_US_CENTRAL = {
    "Texas", "Austin", "Dallas", "Chicago", "Illinois", "Ohio",
    "Michigan", "Indiana", "Wisconsin", "Minnesota", "Iowa", "Missouri",
    "Kansas", "Oklahoma", "Arkansas", "Tennessee", "Kentucky", "Alabama",
    "Mississippi", "Louisiana", "Colorado", "Wyoming", "Montana",
    "New Mexico", "Arizona", "Utah", "Idaho", "Nebraska",
}
_US_WEST_COAST = {
    "San Francisco", "California", "Oregon", "Washington", "Nevada",
    "Alaska", "Hawaii",
}
_UK_LOCS = {"London", "UK", "United Kingdom"}
_CANADA_LOCS = {"Ontario", "Toronto", "Vancouver", "Quebec", "Canada"}

# Senior leaders without an explicit city — default region "Global" so
# they aren't accidentally tagged to a single coast.
_NO_LOC_GLOBAL = True


def _location_to_region_country(loc: str | None) -> tuple[list[str], str | None]:
    """Map a free-text location string to (regions, country). Conservative —
    returns empty regions if the location doesn't match a known bucket."""
    if not loc:
        return ([], None)
    s = loc.strip()
    if s in _UK_LOCS:
        return (["UK", "EMEA"], "United Kingdom")
    if s in _CANADA_LOCS or "Canada" in s or s == "Ontario (Canada)":
        return (["Central"], "Canada")
    if s in _US_EAST_COAST:
        return (["East Coast"], "United States")
    if s in _US_CENTRAL:
        return (["Central"], "United States")
    if s in _US_WEST_COAST:
        return (["West Coast"], "United States")
    return ([], s or None)


# ---------------------------------------------------------------------------
# Email pattern + explicit exceptions
# ---------------------------------------------------------------------------

# Verbatim from the user's roster — preserve case + alt surnames exactly.
EMAIL_OVERRIDES = {
    # Braze — AMER
    "braze-emmanouela-androulaki": "e.androulaki@braze.com",
    "braze-tim-taggart":           "tim.taggart@braze.com",
    "braze-allyson-kurth":         "allyson.kurth@braze.com",
    "braze-stephanie-chang":       "stephanie.chang@braze.com",
    "braze-karin-grant":           "karin.grant@braze.com",
    "braze-amos-lee":              "amos.lee@braze.com",
    "braze-brynne-naylor":         "brynne.naylor@braze.com",
    "braze-bea-dicarlo":           "elizabeth.dicarlo@braze.com",
    "braze-kayleen-duffy":         "kayleen.duffy@braze.com",
    "braze-michael-conway":        "michael.conway@braze.com",
    "braze-melissa-kolano":        "melissa.kolano@braze.com",
    "braze-scott-sigman":          "scott.sigman@braze.com",
    "braze-quentin-favia":         "quentin.favia@braze.com",
    "braze-alex-wise":             "alexander.wise@braze.com",
    "braze-sim-singh":             "sim.singh@braze.com",
    "braze-samantha-crepeau":      "Samantha.Crepeau@braze.com",
    "braze-josh-broner":           "joshua.broner@braze.com",
    "braze-katerina-karousos":     "katerina.karousos@braze.com",
    "braze-andrea-berg":           "andrea.berg@braze.com",
    "braze-caryn-cormier":         "caryn.cormier@braze.com",
    "braze-danielle-kichar":       "danielle.kichar@braze.com",
    "braze-liz-pfeffer":           "liz.pfeffer@braze.com",
    "braze-cara-motowidlo":        "cara.motowidlo@braze.com",
    "braze-amanda-schenk":         "amanda.schenk@braze.com",
    "braze-liza-levinson":         "liza.levinson@braze.com",
    "braze-artem-yermanov":        "artem.yermanov@braze.com",
    "braze-corey-smith":           "corey.smith@braze.com",
    "braze-don-watts":             "don.watts@braze.com",
    "braze-mallory-saunders":      "mallory.saunders@braze.com",
    "braze-kiara-garcia":          "kiara.garcia@braze.com",
    "braze-gina-van-loon":         "gina.vanloon@braze.com",
    "braze-monica-finnigan":       "monica.finnigan@braze.com",
    "braze-kevin-chaney":          "kevin.chaney@braze.com",
    "braze-aileen-waugh":          "aileen.cole@braze.com",       # prior surname Cole
    "braze-julia-gulla":           "julia.shaffer@braze.com",     # prior surname Shaffer
    "braze-karl-flesher":          "karl.flesher@braze.com",
    "braze-kirby-dubose":          "kirby.dubose@braze.com",
    "braze-alexander-mendlen":     "alex.mendlen@braze.com",
    "braze-jacob-deangeles":       "jacob.deangeles@braze.com",
    "braze-josh-marder":           "joshua.marder@braze.com",
    "braze-brian-monachello":      "brian.monachello@braze.com",
    "braze-nader-taghavi":         "nader@braze.com",             # first name only
    "braze-evan-knowles":          "evan.knowles@braze.com",
    "braze-gavin-bennett":         "gavin.bennett@braze.com",
    "braze-keara-cornell":         "keara.cornell@braze.com",
    "braze-skylar-bolender":       "skylar.bolender@braze.com",
    "braze-marcus-trigueros":      "marcus.trigueros@braze.com",
    "braze-john-harper":           "john.harper@braze.com",
    "braze-hannah-miller":         "hannah.slowey@braze.com",     # prior surname Slowey
    "braze-eleanor-wolf":          "eleanor.carman@braze.com",    # formerly Eleanor Carman
    "braze-sean-grove":            "sean.grove@braze.com",
    "braze-marina-klusas":         "Marina.Klusas@braze.com",
    "braze-grant-baughman":        "grant.baughman@braze.com",
    "braze-melanie-scannell":      "melanie.scannell@braze.com",
    "braze-jeff-hannan":           "jeffrey.hannan@braze.com",
    "braze-paul-niedermier":       "paul.niedermier@braze.com",
    "braze-nadina-perera":         "nadina.perera@braze.com",
    "braze-trevor-hawley":         "trevor.hawley@braze.com",
    "braze-kristin-ennuso":        "Kristin.Ennuso@braze.com",
    "braze-allie-shimer":          "allison.shimer@braze.com",
    "braze-sophie-mitchell":       "sophie.mitchell@braze.com",
    "braze-cass-cross":            "cass.cross@braze.com",
    "braze-ryan-fish":             "ryan.fish@braze.com",
    "braze-justin-salsberg":       "justin.salsberg@braze.com",
    "braze-meg-baird":             "meg.baird@braze.com",
    "braze-will-lochtefeld":       "will.lochtefeld@braze.com",
    "braze-kiley-naylor":          "kiley@braze.com",             # first name only
    "braze-danielle-collins":      "danielle.collins@braze.com",
    "braze-tim-heller":            "tim.heller@braze.com",
    "braze-megan-lumetta":         "megan.lumetta@braze.com",
    "braze-mats-menhardt":         "mats.menhardt@braze.com",
    "braze-lydia-eager":           "Lydia.Eager@braze.com",
    "braze-lily-jiang":            "Lily.Jiang@braze.com",
    "braze-jacob-eilks":           "jacob.eilks@braze.com",
    "braze-maddie-kessel":         "Maddie.Kessel@braze.com",
    "braze-laurance-piner":        "Laurance.Piner@braze.com",
    "braze-camryn-crang":          "Camryn.Crang@braze.com",
    "braze-hannah-collins":        "hannah.collins@braze.com",
    "braze-lily-sloan":            "lily.sloan@braze.com",
    "braze-michael-senter":        "michael.senter@braze.com",
    "braze-andrew-schmahl":        "Andrew.Schmahl@braze.com",
    "braze-christopher-rapp":      "Christopher.Rapp@braze.com",
    "braze-gina-berg":             "Gina.Berg@braze.com",
    "braze-grace-folz":            "Grace.Folz@braze.com",
    "braze-janie-dickerson":       "Janie.Dickerson@braze.com",
    "braze-liz-satterthwaite":     "Liz.Satterthwaite@braze.com",
    "braze-madelyn-allor":         "Madelyn.Allor@braze.com",
    "braze-matt-skotz":            "matt.skotz@braze.com",
    "braze-brian-spenk":           "brian.spenk@braze.com",
    "braze-emily-ashwell":         "emily.ashwell@braze.com",
    "braze-greta-basley":          "greta.basley@braze.com",
    "braze-jillian-berno":         "jillian.berno@braze.com",
    "braze-kendall-hogenmiller":   "kendall.hogenmiller@braze.com",
    "braze-lauren-tyus":           "lauren.tyus@braze.com",
    "braze-natalie-stillpass":     "natalie.stillpass@braze.com",
    "braze-haris-naeem":           "haris.naeem@braze.com",
    # Braze — EMEA
    "braze-emily-booth":           "emily.booth@braze.com",
    "braze-fergus-walsh":          "fergus.walsh@braze.com",
    "braze-lucy-mair":             "lucy.mair@braze.com",
    "braze-fay-taylor":            "fay.taylor@braze.com",
    "braze-tessa-reed":            "tessa.reed@braze.com",
    "braze-tom-lucas":             "tom.lucas@braze.com",
    "braze-josie-gardner":         "josie.gardner@braze.com",
    "braze-venetia-mccready":      "venetia.mccready@braze.com",
    "braze-tom-peters":            "tom.peters@braze.com",
    "braze-bailey-ruthven":        "bailey.ruthven@braze.com",
    "braze-ben-rudgley":           "ben.rudgley@braze.com",
    # Braze — Partner org
    "braze-glenn-bonforte":        "glenn.bonforte@braze.com",
    "braze-james-dobson":          "james.dobson@braze.com",
    "braze-sam-oresanya":          "sam.oresanya@braze.com",
    "braze-haatim-ahmed":          "haatim.ahmed@braze.com",
    "braze-renata-minami":         "renata.minami@braze.com",
    "braze-harry-fellows":         "harry.fellows@braze.com",
    "braze-wenzel-hilpert":        "wenzel.hilpert@braze.com",
}


def _slug(name: str) -> str:
    """Stable slug-from-name for contact IDs. Lowercase, hyphenated,
    handles parens / commas."""
    s = name.lower()
    s = re.sub(r"\([^)]*\)", " ", s)        # drop parenthetical
    s = re.sub(r"[^a-z0-9]+", "-", s)
    s = re.sub(r"-+", "-", s).strip("-")
    return s


def _infer_email(name: str, domain: str) -> str:
    """firstname.lastname@<domain>, lowercase, parenthetical stripped."""
    cleaned = re.sub(r"\([^)]*\)", " ", name).strip()
    parts = [p for p in re.split(r"\s+", cleaned) if p]
    if len(parts) < 2:
        local = parts[0] if parts else "unknown"
    else:
        # Use first + LAST token (skip middle names). Lowercased.
        local = f"{parts[0]}.{parts[-1]}"
    local = re.sub(r"[^a-z0-9.]+", "", local.lower())
    return f"{local}@{domain}"


# ---------------------------------------------------------------------------
# MR-priority list — tighter cadence + visible tag
# ---------------------------------------------------------------------------

# Slugs of contacts on Ben's top-priority list (see his profile memory).
# These get cadence_days=14 + "mr_priority" tag so they bubble up in the
# overdue queue.
MR_PRIORITY_SLUGS = {
    "braze-marina-klusas",
    "braze-william-thomas",
    "braze-eric-sanders",
    "braze-stephanie-chang",
    "braze-eleanor-wolf",
    "braze-marlon-hills",
    "braze-katie-cornwell",
    "braze-glenn-bonforte",
}


# ---------------------------------------------------------------------------
# Roster — every Braze + Hightouch contact, with reporting lines
# ---------------------------------------------------------------------------
#
# Each entry is a 6-tuple:
#   (name, title, manager_slug | None, segment | "", industries [list], location)
#
# segment maps to `territories` (a single-element list when present).
# industries maps to `industries`.
# location maps to (regions, country) via _location_to_region_country.

BRAZE_ROSTER: list[tuple[str, str, str | None, str, list[str], str | None]] = [
    # ───── AMER leadership tree ─────
    ("Eric Sanders",            "SVP, Sales",                              None,                            "",                     [],                       "NYC"),
    ("Jason Swetnam",           "SVP, North America",                      "braze-eric-sanders",            "",                     [],                       "NYC"),
    ("Lindsey Swanson",         "SVP",                                     "braze-eric-sanders",            "",                     [],                       None),
    ("Haris Naeem",             "Enterprise AE — GCC",                     "braze-eric-sanders",            "Enterprise",           [],                       None),

    ("Scott Gibson",            "VP, Industry Sales",                      "braze-jason-swetnam",           "",                     [],                       "Texas"),
    ("Emmanouela Androulaki",   "VP, General Business",                    "braze-jason-swetnam",           "",                     [],                       "NYC"),
    ("Tim Taggart",             "VP, Commercial — General Business",       "braze-jason-swetnam",           "",                     [],                       "San Francisco"),

    # ───── Scott Gibson → Allyson Kurth (MEGS) ─────
    ("Allyson Kurth",           "AVP, MEGS",                               "braze-scott-gibson",            "",                     [],                       "San Francisco"),

    ("Karin Grant",             "SD, Strategic",                           "braze-allyson-kurth",           "Strategic Enterprise", [],                       "Dallas"),
    ("Amos Lee",                "Account Executive, Strategic",            "braze-karin-grant",             "Strategic Enterprise", [],                       "San Francisco"),
    ("Brynne Naylor",           "Account Executive, Strategic",            "braze-karin-grant",             "Strategic Enterprise", [],                       "NYC"),
    ("Bea DiCarlo",             "Account Executive, Strategic",            "braze-karin-grant",             "Strategic Enterprise", [],                       "San Francisco"),
    ("Kayleen Duffy",           "Account Executive, Strategic",            "braze-karin-grant",             "Strategic Enterprise", [],                       "NYC"),

    ("Michael Conway",          "SD, Enterprise",                          "braze-allyson-kurth",           "Enterprise",           [],                       "San Francisco"),
    ("Melissa Kolano",          "Account Executive, Enterprise",           "braze-michael-conway",          "Enterprise",           [],                       "New Jersey"),
    ("Scott Sigman",            "Account Executive, Enterprise",           "braze-michael-conway",          "Enterprise",           [],                       "Colorado"),
    ("Quentin Favia",           "Account Executive, Emerging Enterprise",  "braze-michael-conway",          "Emerging Enterprise",  [],                       "NYC"),
    ("Alex Wise",               "Account Executive, Enterprise",           "braze-michael-conway",          "Enterprise",           [],                       "California"),

    ("Sim Singh",               "SD, Scale",                               "braze-allyson-kurth",           "Scale",                [],                       "NYC"),
    ("Samantha Crepeau",        "Account Executive, Scale",                "braze-sim-singh",               "Scale",                [],                       "California"),
    ("Josh Broner",             "Account Executive, Scale",                "braze-sim-singh",               "Scale",                [],                       "NYC"),
    ("Katerina Karousos",       "Account Executive, Scale",                "braze-sim-singh",               "Scale",                [],                       "NYC"),
    ("Andrea Berg",             "Account Executive, Scale",                "braze-sim-singh",               "Scale",                [],                       "Chicago"),

    # ───── Scott Gibson → Stephanie Chang (Retail) ─────
    ("Stephanie Chang",         "AVP, Retail",                             "braze-scott-gibson",            "",                     ["Retail"],               "Austin"),

    ("Caryn Cormier",           "SD, Strategic Retail",                    "braze-stephanie-chang",         "Strategic Enterprise", ["Retail"],               "San Francisco"),
    ("Danielle Kichar",         "Account Executive, Strategic Retail",     "braze-caryn-cormier",           "Strategic Enterprise", ["Retail"],               "Texas"),
    ("Liz Pfeffer",             "Account Executive, Strategic Retail",     "braze-caryn-cormier",           "Strategic Enterprise", ["Retail"],               "NYC"),
    ("Cara Motowidlo",          "Account Executive, Strategic Retail",     "braze-caryn-cormier",           "Strategic Enterprise", ["Retail"],               "South Carolina"),
    ("Amanda Schenk",           "Account Executive, Strategic Retail",     "braze-caryn-cormier",           "Strategic Enterprise", ["Retail"],               "NYC"),
    ("Liza Levinson",           "Account Executive, Strategic Retail",     "braze-caryn-cormier",           "Strategic Enterprise", ["Retail"],               "Florida"),

    ("Artem Yermanov",          "SD, Enterprise Retail",                   "braze-stephanie-chang",         "Enterprise",           ["Retail"],               "California"),
    ("Corey Smith",             "Account Executive, Enterprise Retail",    "braze-artem-yermanov",          "Enterprise",           ["Retail"],               "Massachusetts"),
    ("Don Watts",               "Account Executive, Enterprise Retail",    "braze-artem-yermanov",          "Enterprise",           ["Retail"],               "Chicago"),
    ("Mallory Saunders",        "Account Executive, Enterprise Retail",    "braze-artem-yermanov",          "Enterprise",           ["Retail"],               "Austin"),
    ("Kiara Garcia",            "Account Executive, Enterprise Retail",    "braze-artem-yermanov",          "Enterprise",           ["Retail"],               "Austin"),

    ("Gina Van Loon",           "SD, Emerging Enterprise Retail",          "braze-stephanie-chang",         "Emerging Enterprise",  ["Retail"],               "San Francisco"),
    ("Monica Finnigan",         "Account Executive, Emerging Enterprise",  "braze-gina-van-loon",           "Emerging Enterprise",  ["Retail"],               "San Francisco"),
    ("Kevin Chaney",            "Account Executive, Emerging Enterprise",  "braze-gina-van-loon",           "Emerging Enterprise",  ["Retail"],               "San Francisco"),
    ("Aileen Waugh",            "Account Executive, Emerging Enterprise",  "braze-gina-van-loon",           "Emerging Enterprise",  ["Retail"],               "Georgia"),
    ("Julia Gulla",             "Account Executive, Emerging Enterprise",  "braze-gina-van-loon",           "Emerging Enterprise",  ["Retail"],               "NYC"),
    ("Karl Flesher",            "Account Executive, Scale Retail",         "braze-gina-van-loon",           "Scale",                ["Retail"],               "Chicago"),
    ("Kirby DuBose",            "Account Executive, Scale Retail",         "braze-gina-van-loon",           "Scale",                ["Retail"],               "San Francisco"),
    ("Alexander Mendlen",       "Account Executive, Scale Retail",         "braze-gina-van-loon",           "Scale",                ["Retail"],               "NYC"),
    ("Jacob DeAngeles",         "Account Executive, Scale Retail",         "braze-gina-van-loon",           "Scale",                ["Retail"],               "San Francisco"),

    # ───── Scott Gibson → FINS (no SD layer) ─────
    ("Josh Marder",             "Account Executive, Strategic — FINS",     "braze-scott-gibson",            "Strategic Enterprise", ["Financial Services"],   "New Hampshire"),
    ("Brian Monachello",        "Account Executive, Enterprise — FINS",    "braze-scott-gibson",            "Enterprise",           ["Financial Services"],   "New Jersey"),
    ("Nader Taghavi",           "Account Executive, Enterprise — FINS",    "braze-scott-gibson",            "Enterprise",           ["Financial Services"],   "Ontario"),
    ("Evan Knowles",            "Account Executive, Emerging Ent — FINS",  "braze-scott-gibson",            "Emerging Enterprise",  ["Financial Services"],   "California"),
    ("Gavin Bennett",           "Account Executive, Emerging Ent — FINS",  "braze-scott-gibson",            "Emerging Enterprise",  ["Financial Services"],   "NYC"),
    ("Keara Cornell",           "Account Executive, Emerging Ent — FINS",  "braze-scott-gibson",            "Emerging Enterprise",  ["Financial Services"],   "NYC"),
    ("Skylar Bolender",         "Account Executive, Scale — FINS",         "braze-scott-gibson",            "Scale",                ["Financial Services"],   "San Francisco"),
    ("Marcus Trigueros",        "Account Executive, Scale — FINS",         "braze-scott-gibson",            "Scale",                ["Financial Services"],   "San Francisco"),
    ("John Harper",             "Account Executive, Scale — FINS",         "braze-scott-gibson",            "Scale",                ["Financial Services"],   "Chicago"),
    ("Hannah Miller",           "Account Executive, Scale — FINS",         "braze-scott-gibson",            "Scale",                ["Financial Services"],   "Chicago"),

    # ───── Emmanouela Androulaki → William Thomas (Strategic GenBiz) ─────
    ("William Thomas",          "SD, Strategic — General Business",        "braze-emmanouela-androulaki",   "Strategic Enterprise", ["QSR"],                  None),
    ("Eleanor Wolf",            "Account Executive, Strategic — GenBiz",   "braze-william-thomas",          "Strategic Enterprise", ["QSR"],                  "Colorado"),
    ("Sean Grove",              "Account Executive, Strategic — GenBiz",   "braze-william-thomas",          "Strategic Enterprise", ["QSR"],                  "Oregon"),
    ("Marina Klusas",           "Strategic Enterprise AE — CPG",           "braze-william-thomas",          "Strategic Enterprise", ["QSR"],                  "Virginia"),

    # Emmanouela direct reports (no SD)
    ("Grant Baughman",          "Enterprise AE — General Business",        "braze-emmanouela-androulaki",   "Enterprise",           [],                       "Connecticut"),
    ("Melanie Scannell",        "Enterprise AE — General Business",        "braze-emmanouela-androulaki",   "Enterprise",           [],                       "San Francisco"),
    ("Jeff Hannan",             "Enterprise AE — General Business",        "braze-emmanouela-androulaki",   "Enterprise",           [],                       "California"),
    ("Paul Niedermier",         "Enterprise AE — General Business",        "braze-emmanouela-androulaki",   "Enterprise",           [],                       "San Francisco"),
    ("Nadina Perera",           "Enterprise AE — Travel & Hospitality",    "braze-emmanouela-androulaki",   "Enterprise",           ["Travel & Hospitality"], "Massachusetts"),
    ("Trevor Hawley",           "Enterprise AE — QSR & Auto",              "braze-emmanouela-androulaki",   "Enterprise",           ["QSR"],                  "NYC"),

    ("Kristin Ennuso",          "SD, Emerging Enterprise — GenBiz",        "braze-emmanouela-androulaki",   "Emerging Enterprise",  [],                       "Chicago"),
    ("Allie Shimer",            "Account Executive, Emerging Enterprise",  "braze-kristin-ennuso",          "Emerging Enterprise",  [],                       "Chicago"),
    ("Sophie Mitchell",         "Account Executive, Emerging Enterprise",  "braze-kristin-ennuso",          "Emerging Enterprise",  [],                       "NYC"),
    ("Cass Cross",              "Account Executive, Emerging Enterprise",  "braze-kristin-ennuso",          "Emerging Enterprise",  [],                       "Chicago"),
    ("Ryan Fish",               "Account Executive, Emerging Enterprise",  "braze-kristin-ennuso",          "Emerging Enterprise",  [],                       "San Francisco"),

    # ───── Tim Taggart → Commercial scale teams ─────
    ("Justin Salsberg",         "SD, Scale — General Business",            "braze-tim-taggart",             "Scale",                [],                       "Ontario"),
    ("Meg Baird",               "Account Executive, Scale",                "braze-justin-salsberg",         "Scale",                [],                       "Chicago"),
    ("Bernardo Cabrera",        "Account Executive, Scale",                "braze-justin-salsberg",         "Scale",                [],                       "NYC"),
    ("Will Lochtefeld",         "Account Executive, Scale",                "braze-justin-salsberg",         "Scale",                [],                       "NYC"),
    ("Kiley Naylor",            "Account Executive, Scale",                "braze-justin-salsberg",         "Scale",                [],                       "San Francisco"),

    ("Danielle Collins",        "SD, Scale",                               "braze-tim-taggart",             "Scale",                [],                       "NYC"),
    ("Tim Heller",              "Account Executive, Scale",                "braze-danielle-collins",        "Scale",                [],                       "NYC"),
    ("Megan Lumetta",           "Account Executive, Scale",                "braze-danielle-collins",        "Scale",                [],                       "Chicago"),
    ("Al Willett",              "Account Executive, Scale",                "braze-danielle-collins",        "Scale",                [],                       "Chicago"),
    ("Mats Menhardt",           "Account Executive, Scale",                "braze-danielle-collins",        "Scale",                [],                       "San Francisco"),
    ("Lydia Eager",             "Account Executive, Scale",                "braze-danielle-collins",        "Scale",                [],                       "Austin"),
    ("Lily Jiang",              "Account Executive, Scale",                "braze-danielle-collins",        "Scale",                [],                       "NYC"),

    ("Jacob Eilks",             "SD, Scale — General Business (NB)",       "braze-tim-taggart",             "Scale",                [],                       "Chicago"),
    ("Maddie Kessel",           "Account Executive, Scale",                "braze-jacob-eilks",             "Scale",                [],                       "Ontario"),
    ("Laurance Piner",          "Account Executive, Scale",                "braze-jacob-eilks",             "Scale",                [],                       "Chicago"),
    ("Camryn Crang",            "Account Executive, Scale",                "braze-jacob-eilks",             "Scale",                [],                       "NYC"),
    ("Hannah Collins",          "Account Executive, Scale",                "braze-jacob-eilks",             "Scale",                [],                       "Austin"),
    ("Lily Sloan",              "Account Executive, Scale",                "braze-jacob-eilks",             "Scale",                [],                       "Chicago"),

    ("Michael Senter",          "SD, Braze for SUs — General Business",    "braze-tim-taggart",             "Scale",                [],                       "Austin"),
    ("Andrew Schmahl",          "Account Executive, Braze for SUs",        "braze-michael-senter",          "Scale",                [],                       "Chicago"),
    ("Christopher Rapp",        "Account Executive, Braze for SUs",        "braze-michael-senter",          "Scale",                [],                       "Austin"),
    ("Gina Berg",               "Account Executive, Braze for SUs",        "braze-michael-senter",          "Scale",                [],                       "Chicago"),
    ("Grace Folz",              "Account Executive, Braze for SUs",        "braze-michael-senter",          "Scale",                [],                       "Chicago"),
    ("Janie Dickerson",         "Account Executive, Braze for SUs",        "braze-michael-senter",          "Scale",                [],                       "Chicago"),
    ("Liz Satterthwaite",       "Account Executive, Braze for SUs",        "braze-michael-senter",          "Scale",                [],                       "Austin"),
    ("Madelyn Allor",           "Account Executive, Braze for SUs",        "braze-michael-senter",          "Scale",                [],                       "Chicago"),
    ("Matt Skotz",              "Account Executive, Braze for SUs",        "braze-michael-senter",          "Scale",                [],                       "Austin"),

    # ───── Lindsey Swanson → Ava Lillian ─────
    ("Ava Lillian",             "AVP",                                     "braze-lindsey-swanson",         "",                     [],                       None),
    ("Brian Spenk",             "Account Executive, Emerging Enterprise",  "braze-ava-lillian",             "Emerging Enterprise",  [],                       "Chicago"),
    ("Caitlin Wood",            "Account Executive, Emerging Enterprise",  "braze-ava-lillian",             "Emerging Enterprise",  [],                       "NYC"),
    ("Emily Ashwell",           "Account Executive, Strategic",            "braze-ava-lillian",             "Strategic Enterprise", [],                       "California"),
    ("Greta Basley",            "Account Executive, Strategic",            "braze-ava-lillian",             "Strategic Enterprise", [],                       "NYC"),
    ("Jillian Berno",           "Account Executive, Enterprise — Retail",  "braze-ava-lillian",             "Enterprise",           ["Retail"],               "New Jersey"),
    ("Kendall Hogenmiller",     "Account Executive, Strategic",            "braze-ava-lillian",             "Strategic Enterprise", [],                       "Austin"),
    ("Lauren Tyus",             "Account Executive, Enterprise",           "braze-ava-lillian",             "Enterprise",           [],                       "Ohio"),
    ("Natalie Stillpass",       "Account Executive, Enterprise",           "braze-ava-lillian",             "Enterprise",           [],                       "NYC"),

    # ───── EMEA tree ─────
    ("Marc Suchland",           "SVP, EMEA",                               "braze-eric-sanders",            "",                     [],                       None),
    ("Marlon Hills",            "VP, EMEA",                                "braze-marc-suchland",           "",                     [],                       "London"),

    ("Zarpana Kabir",           "AVP — Northern Europe",                   "braze-marlon-hills",            "",                     [],                       "London"),
    ("Emily Booth",             "Enterprise AE — Retail (NE)",             "braze-zarpana-kabir",           "Enterprise",           ["Retail"],               "London"),
    ("Fergus Walsh",            "Enterprise AE (NE)",                      "braze-zarpana-kabir",           "Enterprise",           [],                       "London"),
    ("Lucy Mair",               "Enterprise AE (NE)",                      "braze-zarpana-kabir",           "Enterprise",           [],                       "London"),
    ("Fay Taylor",              "Enterprise AE (NE)",                      "braze-zarpana-kabir",           "Enterprise",           [],                       "London"),

    ("Tessa Reed",              "Emerging Enterprise AE (NE)",             "braze-marlon-hills",            "Emerging Enterprise",  [],                       "London"),
    ("Tom Lucas",               "Emerging Enterprise AE (NE)",             "braze-marlon-hills",            "Emerging Enterprise",  [],                       "London"),

    ("George Goodger",          "AVP — Scale (NE)",                        "braze-marlon-hills",            "Scale",                [],                       "London"),
    ("Josie Gardner",           "Scale AE (NE)",                           "braze-george-goodger",          "Scale",                [],                       "London"),
    ("Venetia McCready",        "Scale AE (NE)",                           "braze-george-goodger",          "Scale",                [],                       "London"),
    ("Tom Peters",              "Scale AE (NE)",                           "braze-george-goodger",          "Scale",                [],                       "London"),
    ("Bailey Ruthven",          "Scale AE (NE)",                           "braze-george-goodger",          "Scale",                [],                       "London"),
    ("Ben Rudgley",             "Scale AE (NE)",                           "braze-george-goodger",          "Scale",                [],                       "London"),

    # EMEA — additional contacts (relationship/legacy; manager TBC)
    ("Katie Cornwell",          "EMEA contact — Shell EMEA",               "braze-marlon-hills",            "Enterprise",           [],                       "London"),
    ("Imi de Daranyi",          "Strategic Enterprise AE — McDonald's / Yum", None,                          "Strategic Enterprise", ["QSR"],                  "London"),
    ("Rod Aimes",               "VP (legacy reference)",                   None,                            "",                     [],                       "London"),
    ("Abigail Tucker",          "Enterprise Sales Director — QSR/Tech",    None,                            "Enterprise",           ["QSR"],                  "London"),
    ("Jase Buckley",            "Enterprise Sales Director — FINS",        None,                            "Enterprise",           ["Financial Services"],   "London"),

    # ───── Braze — GSA / Solutions Architects ─────
    ("Nish Patel",              "Global Solutions Architect",              None,                            "",                     [],                       "London"),
    ("Heather",                 "Global Solutions Architect (surname TBD)", None,                           "",                     [],                       "London"),

    # ───── Braze — Customer Success ─────
    ("Georgia Harrison",        "Customer Success Manager",                None,                            "",                     ["QSR"],                  "London"),
    ("Ashley Wilkinson",        "Customer Success Manager",                None,                            "",                     [],                       None),
    ("Orlando Beakbane",        "Customer Success Manager",                None,                            "",                     [],                       None),

    # ───── Braze — Partner org (Glenn + co-sell circle) ─────
    ("Glenn Bonforte",          "Senior Partner Success Manager",          None,                            "",                     [],                       None),
    ("James Dobson",            "Partner team",                            "braze-glenn-bonforte",          "",                     [],                       None),
    ("Sam Oresanya",            "Partner team",                            "braze-glenn-bonforte",          "",                     [],                       None),
    ("Haatim Ahmed",            "Partner team",                            "braze-glenn-bonforte",          "",                     [],                       None),
    ("Renata Minami",           "Partner team",                            "braze-glenn-bonforte",          "",                     [],                       None),
    ("Harry Fellows",           "Partner team",                            "braze-glenn-bonforte",          "",                     [],                       None),
    ("Wenzel Hilpert",          "Partner team",                            "braze-glenn-bonforte",          "",                     [],                       None),
]


# Hightouch — North America Sales. No explicit emails given; all
# inferred via firstname.lastname@hightouch.com (tagged email_inferred).
HIGHTOUCH_ROSTER: list[tuple[str, str, str | None, str, list[str], str | None]] = [
    # Roots — no parent given (assume both report into Hightouch CRO).
    ("Vinod Venkatasubramaniam", "Head of Enterprise Sales, West",         None, "Strategic Enterprise", [], None),
    ("John Knudsen",             "Head of Mid-Market Sales, North (East)", None, "Mid-Market",           [], None),

    # John Knudsen → Joseph Spath (Mid-Market East)
    ("Joseph Spath",             "Head of Mid-Market Sales, East",         "ht-john-knudsen",  "Mid-Market", [], None),
    ("Dan Gomez",                "Account Executive, Mid-Market",          "ht-joseph-spath",  "Mid-Market", [], None),
    ("Allan Bronzo",             "Account Executive, Mid-Market",          "ht-joseph-spath",  "Mid-Market", [], None),
    ("Azure Aladin",             "Sr. Account Executive, Mid-Market",      "ht-joseph-spath",  "Mid-Market", [], None),
    ("Kellie Best",              "Sr. Account Executive, Mid-Market",      "ht-joseph-spath",  "Mid-Market", [], None),
    ("Jill Healy",               "Account Executive, Mid-Market",          "ht-joseph-spath",  "Mid-Market", [], None),
    ("Rebecca Schrager",         "Sr. Account Executive, Mid-Market",      "ht-joseph-spath",  "Mid-Market", [], None),
    ("Shelby Lane",              "Sr. Account Executive, Mid-Market",      "ht-joseph-spath",  "Mid-Market", [], None),
    ("Meredith Taylor",          "Account Executive, Mid-Market",          "ht-joseph-spath",  "Mid-Market", [], None),
    ("Marlowe Brand",            "Sr. Account Executive, Mid-Market",      "ht-joseph-spath",  "Mid-Market", [], None),
    ("Meghan Summers",           "Account Executive, Mid-Market",          "ht-joseph-spath",  "Mid-Market", [], None),
    ("Aidan O'Connell",          "Account Executive, Mid-Market",          "ht-joseph-spath",  "Mid-Market", [], None),

    # John Knudsen → Jessica Doyle (Mid-Market Central — header says 6, 3 listed)
    ("Jessica Doyle",            "Manager, Mid-Market Sales Central",      "ht-john-knudsen",  "Mid-Market", [], None),
    ("Ryan Nardi",               "Account Executive, Mid-Market",          "ht-jessica-doyle", "Mid-Market", [], None),
    ("Sonia Del Rivo",           "Account Executive, Mid-Market",          "ht-jessica-doyle", "Mid-Market", [], None),
    ("Mike Rizzo",               "Sr. Account Executive, Mid-Market",      "ht-jessica-doyle", "Mid-Market", [], None),

    # John Knudsen → Trevor Sutley (player-coach)
    ("Trevor Sutley",            "Account Executive, Mid-Market (lead)",   "ht-john-knudsen",  "Mid-Market", [], None),
    ("Austin Collier",           "Account Executive, Mid-Market",          "ht-trevor-sutley", "Mid-Market", [], None),
    ("Robinson Smith",           "Sr. Account Executive, Mid-Market",      "ht-trevor-sutley", "Mid-Market", [], None),
    ("Jonathan McDonald",        "Account Executive, Mid-Market",          "ht-trevor-sutley", "Mid-Market", [], None),

    # Vinod → Alex Matthews (Enterprise West)
    ("Alex Matthews",            "Manager, Enterprise Sales West",         "ht-vinod-venkatasubramaniam", "Enterprise", [], None),
    ("Nick Schrader",            "Account Executive, Enterprise",          "ht-alex-matthews", "Enterprise", [], None),
    ("Jace Dicker",              "Account Executive, Enterprise",          "ht-alex-matthews", "Enterprise", [], None),
    ("Joe Boyle",                "Account Executive, Enterprise",          "ht-alex-matthews", "Enterprise", [], None),
    ("Alex Tirion",              "Account Executive, Enterprise",          "ht-alex-matthews", "Enterprise", [], None),
    ("Sam Loppnow",              "Account Executive, Enterprise",          "ht-alex-matthews", "Enterprise", [], None),
    ("Ian Lonsdale",             "Account Executive, Enterprise",          "ht-alex-matthews", "Enterprise", [], None),
    ("Ryan Minsker",             "Sr. Account Executive, Enterprise",      "ht-alex-matthews", "Enterprise", [], None),

    # Vinod → Kyla Gundersen (Enterprise West)
    ("Kyla Gundersen",           "Manager, Enterprise Sales West",         "ht-vinod-venkatasubramaniam", "Strategic Enterprise", [], None),
    ("Matt Whittle",             "Sr. Account Executive, Enterprise",      "ht-kyla-gundersen", "Enterprise", [], None),
    ("Mark Leedy",               "Sr. Account Executive, Enterprise",      "ht-kyla-gundersen", "Enterprise", [], None),
    ("J.D. Mooney",              "Account Executive, Enterprise",          "ht-kyla-gundersen", "Enterprise", [], None),
    ("Ryan McReynolds",          "Account Executive, Enterprise",          "ht-kyla-gundersen", "Enterprise", [], None),
    ("Aly Ausen",                "Strategic Account Executive",            "ht-kyla-gundersen", "Strategic Enterprise", [], None),
    ("Taylor Gunter",            "Account Executive, Enterprise",          "ht-kyla-gundersen", "Enterprise", [], None),

    # Vinod → Blake Ballardo (Client Account Director — existing-customer expansion)
    ("Blake Ballardo",           "Client Account Director, West",          "ht-vinod-venkatasubramaniam", "Strategic Enterprise", [], None),
    ("Allie Williams",           "Account Executive, Enterprise",          "ht-blake-ballardo", "Enterprise", [], None),
    ("Colleen Callahan",         "Account Executive, Enterprise",          "ht-blake-ballardo", "Enterprise", [], None),
    ("Julie Ann Carey",          "Account Executive, Enterprise",          "ht-blake-ballardo", "Enterprise", [], None),

    # Vinod → Aidan Lynch (APAC — out of MR scope)
    ("Aidan Lynch",              "Sales Manager, APAC",                    "ht-vinod-venkatasubramaniam", "Enterprise", [], None),
    ("Meghan Miller",            "Strategic Account Executive",            "ht-aidan-lynch", "Strategic Enterprise", [], None),

    # Vinod → direct (no manager layer)
    ("Glenn Pacitti",            "Strategic Account Executive",            "ht-vinod-venkatasubramaniam", "Strategic Enterprise", [], None),
]


# ---------------------------------------------------------------------------
# Render: turn the compact roster into save-ready dicts
# ---------------------------------------------------------------------------

def _build_contacts(
    roster: list[tuple[str, str, str | None, str, list[str], str | None]],
    *,
    slug_prefix: str,
    email_domain: str,
) -> list[dict[str, Any]]:
    """Expand a roster into full contact dicts ready for save_contact."""
    out: list[dict[str, Any]] = []
    for name, title, manager, segment, industries, location in roster:
        cid = f"{slug_prefix}-{_slug(name)}"
        regions, country = _location_to_region_country(location)

        # Email: explicit override > inferred.
        override = EMAIL_OVERRIDES.get(cid)
        if override:
            email = override
            inferred = False
        else:
            email = _infer_email(name, email_domain)
            inferred = True

        # Tags: every contact gets the command_centre_seed tag.
        tags = ["command_centre_seed"]
        if inferred:
            tags.append("email_inferred")
        if cid in MR_PRIORITY_SLUGS:
            tags.append("mr_priority")
        # Flag the legacy/cross-team confirmation-required folks
        if cid in {
            "braze-imi-de-daranyi",
            "braze-rod-aimes",
            "braze-abigail-tucker",
            "braze-jase-buckley",
            "braze-heather",
        }:
            tags.append("confirm_org")

        # Cadence: priority list → tighter; SVP/VP → 21d; everyone else 30d.
        if cid in MR_PRIORITY_SLUGS:
            cadence = 14
        elif title.startswith(("SVP", "VP", "AVP", "Head ", "Senior Partner")):
            cadence = 21
        else:
            cadence = 30

        out.append({
            "id":            cid,
            "name":          name,
            "title":         title,
            "email":         email,
            "territories":   [segment] if segment else [],
            "regions":       regions,
            "country":       country,
            "industries":    industries,
            "mr_owner":      "Ben Ojuolape",
            "status":        "active",
            "cadence_days":  cadence,
            "reports_to_id": manager,
            "tags":          tags,
        })
    return out


BRAZE_CONTACTS = _build_contacts(BRAZE_ROSTER, slug_prefix="braze", email_domain="braze.com")
HIGHTOUCH_CONTACTS = _build_contacts(HIGHTOUCH_ROSTER, slug_prefix="ht", email_domain="hightouch.com")


# ---------------------------------------------------------------------------
# Seed runner
# ---------------------------------------------------------------------------

def _upsert_partner(payload: dict[str, Any]) -> str:
    return partners_store.save_partner(payload)["id"]


def _upsert_contact(partner_id: str, payload: dict[str, Any]) -> str:
    return partner_contacts_store.save_contact(partner_id, payload)["id"]


def seed() -> dict[str, Any]:
    """Apply the seed. Returns a summary dict for the caller."""
    summary = {
        "partners_seeded": [],
        "contacts_seeded": [],
        "contacts_skipped": [],
    }

    # Braze
    braze_id = _upsert_partner(BRAZE_PARTNER)
    summary["partners_seeded"].append({"id": braze_id, "name": BRAZE_PARTNER["name"]})
    for c in BRAZE_CONTACTS:
        try:
            cid = _upsert_contact(braze_id, c)
            summary["contacts_seeded"].append({
                "partner": "Braze", "contact_id": cid, "name": c["name"],
            })
        except partner_contacts_store.PartnerContactsStoreError as e:
            summary["contacts_skipped"].append({"name": c.get("name"), "reason": str(e)})

    # Hightouch
    ht_id = _upsert_partner(HIGHTOUCH_PARTNER)
    summary["partners_seeded"].append({"id": ht_id, "name": HIGHTOUCH_PARTNER["name"]})
    for c in HIGHTOUCH_CONTACTS:
        try:
            cid = _upsert_contact(ht_id, c)
            summary["contacts_seeded"].append({
                "partner": "Hightouch", "contact_id": cid, "name": c["name"],
            })
        except partner_contacts_store.PartnerContactsStoreError as e:
            summary["contacts_skipped"].append({"name": c.get("name"), "reason": str(e)})

    return summary


if __name__ == "__main__":
    s = seed()
    print(f"Seeded {len(s['partners_seeded'])} partners, "
          f"{len(s['contacts_seeded'])} contacts.")
    inferred = [
        c for c in s["contacts_seeded"]
        if any(x["contact_id"] == c["contact_id"]
               and "email_inferred" in (
                   next((d.get("tags", []) for d in BRAZE_CONTACTS + HIGHTOUCH_CONTACTS
                         if d["id"] == c["contact_id"]), []))
               for x in [c])
    ]
    print(f"  - {len(inferred)} of them have inferred emails "
          f"(tag: email_inferred) for audit later.")
    if s["contacts_skipped"]:
        print(f"Skipped {len(s['contacts_skipped'])} contact(s):")
        for c in s["contacts_skipped"]:
            print(f"  - {c.get('name')}: {c.get('reason')}")
    sys.exit(0)
