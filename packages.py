"""
Pre-defined project packages.

Source: `[Reference] Packages` tab in the v2.0 Pricing Calculator Google
Sheet. Each package is a starting point — the AE picks one (or combines a
few), the package's role × hours allocation seeds the resource plan, and
the AE refines from there.

Each package:
    name:         human label, used in the UI picker
    duration_months: typical engagement length in months
    components:   list of {role, activity, days, hours} line items
    total_hours:  pre-computed sum (kept for cheap UI display + sanity)
    notes:        optional one-line description
"""
from __future__ import annotations

from typing import Any


def _pkg(name: str, duration: int, components: list[tuple[str, str, float, int]],
         notes: str = "") -> dict[str, Any]:
    """Build a package dict from the (role, activity, days, hours) tuples."""
    comps = [{"role": r, "activity": a, "days": d, "hours": h}
             for r, a, d, h in components]
    return {
        "name": name,
        "duration_months": duration,
        "components": comps,
        "total_hours": sum(c["hours"] for c in comps),
        "notes": notes,
    }


PACKAGES: dict[str, dict[str, Any]] = {
    "Light Audit": _pkg("Light Audit", 3, [
        ("Client Partner", "Business Case", 0, 0),
        ("CRM Strategist", "CRM Strategy", 4, 32),
        ("Architect", "Architecture", 0.5, 4),
        ("Program Manager", "Project Plan", 0.9, 7),
    ], notes="Standalone audit; small effort."),

    "Audit/Inception": _pkg("Audit/Inception", 3, [
        ("Client Partner", "Business Case", 2, 16),
        ("CRM Strategist", "CRM Strategy", 4, 32),
        ("Architect", "Architecture", 3, 24),
        ("Program Manager", "Project Plan", 1.8, 14),
    ], notes="Full Discovery/Inception package."),

    "Braze Onboarding & Training": _pkg("Braze Onboarding & Training", 3, [
        ("Braze Trainer", "Trainer/IC", 5, 40),
        ("Braze Architect", "Solutions Architect", 2, 16),
        ("Senior Braze Trainer", "Project Lead", 2, 16),
        ("Project coordinator", "Project Coordinator", 1, 8),
    ]),

    "Braze Setup & Configuration": _pkg("Braze Setup & Configuration", 3, [
        ("Program Manager", "Project Planning", 2, 16),
        ("CRM Consultant", "Journey Mapping", 2, 16),
        ("CRM Consultant", "IP Warming", 4, 32),
        ("CRM Consultant", "Braze Platform Setup", 4, 32),
        ("CRM Architect", "Architecture", 2, 16),
        ("CRM Architect", "Complex Use Cases", 2, 16),
        ("CRM Consultant", "Campaign Execution", 4, 32),
        ("CRM Consultant", "Quality Assurance", 2, 16),
        ("Program Manager", "Project Management", 4.4, 35),
    ]),

    "Braze - Migration": _pkg("Braze - Migration", 6, [
        ("CRM Strategist", "Detailed Audit", 4, 32),
        ("Architect", "Architecture", 2, 16),
        ("CRM Consultant", "Data Planning", 2, 16),
        ("Architect", "Complex Use Cases", 4, 32),
        ("CRM Consultant", "IP Warming", 4, 32),
        ("CRM Consultant", "Migration Execution", 4, 32),
        ("CRM Developer", "Email Development", 4, 32),
        ("CRM Consultant", "Quality Assurance", 2, 16),
        ("Program Manager", "Project Management", 5.2, 42),
    ]),

    "[X-small] Braze Operations": _pkg("[X-small] Braze Operations", 1, [
        ("CRM Consultant", "Campaign Planning", 0.2, 2),
        ("CRM Consultant", "Campaign Execution", 1.5, 12),
        ("CRM Consultant", "Quality Assurance", 0.17, 1),
        ("Program Manager", "Project Management", 0.374, 3),
    ], notes="~1 BAU per week or 1 lifecycle per month."),

    "[Small] Braze Operations": _pkg("[Small] Braze Operations", 1, [
        ("CRM Consultant", "Campaign Planning", 2, 16),
        ("CRM Consultant", "Campaign Execution", 2, 16),
        ("CRM Developer", "Email Development", 1, 8),
        ("CRM Consultant", "Quality Assurance", 0.5, 4),
        ("Program Manager", "Project Management", 1.1, 9),
    ], notes="Ongoing. Audit included in month 1."),

    "[Medium] Braze Operations": _pkg("[Medium] Braze Operations", 1, [
        ("CRM Consultant", "Campaign Planning", 4, 32),
        ("CRM Consultant", "Campaign Execution", 4, 32),
        ("CRM Developer", "Email Development", 1, 8),
        ("CRM Consultant", "Quality Assurance", 0.9, 7),
        ("Program Manager", "Project Management", 1.98, 16),
    ], notes="Ongoing. Audit included in month 1."),

    "[Large] Braze Operations": _pkg("[Large] Braze Operations", 1, [
        ("CRM Consultant", "Campaign Planning", 5, 40),
        ("CRM Consultant", "Campaign Execution", 5, 40),
        ("Architect", "Architecture", 2, 16),
        ("Architect", "Complex Use Cases", 2, 16),
        ("CRM Developer", "Email Development", 2, 16),
        ("CRM Consultant", "Quality Assurance", 1.6, 13),
        ("Program Manager", "Project Management", 3.52, 28),
    ], notes="Ongoing. Audit included in month 1."),

    "Customer 360": _pkg("Customer 360", 1, [
        ("CDM Architect", "Data Audit & Planning", 4, 32),
        ("CRM Consultant", "Braze Integration", 4, 32),
        ("CDM Architect", "Data Architecture", 4, 32),
        ("Data Engineer", "Data Management", 4, 32),
        ("Data Engineer", "Data Pipeline Development", 4, 32),
        ("Data Engineer", "Quality Assurance", 4, 32),
        ("Program Manager", "Project Management", 4.8, 38),
    ]),

    "CDP Setup": _pkg("CDP Setup", 6, [
        ("CDM Architect", "Architecture & Roadmap", 4, 32),
        ("CRM Consultant", "Data Planning", 4, 32),
        ("CDM Architect", "Implementation", 16, 128),
        ("Data Engineer", "Quality Assurance", 4.8, 38),
        ("Program Manager", "Project Management", 5.76, 46),
    ]),

    "CDP & Data Operations": _pkg("CDP & Data Operations", 1, [
        ("CDM Architect", "Architecture & Roadmap", 2, 16),
        ("CDM Architect", "Data Planning", 2, 16),
        ("CDM Architect", "Implementation", 16, 128),
        ("Data Engineer", "Quality Assurance", 4, 32),
        ("Program Manager", "Project Management", 4.8, 38),
    ]),

    "Salesforce Connector": _pkg("Salesforce Connector", 3, [
        ("CRM Consultant", "Business Requirements", 1, 8),
        ("Engineer", "Environment setup", 1, 8),
        ("Engineer", "Connector Implementation", 5, 40),
        ("Engineer", "Historical Data import", 5, 40),
        ("Engineer", "Quality Assurance", 2.2, 18),
        ("Program Manager", "Project Management", 2.64, 21),
    ]),

    "Braze SDK Integration": _pkg("Braze SDK Integration", 2, [
        ("CRM Consultant", "Data planning", 4, 32),
        ("Engineer", "Integration", 10, 80),
        ("Engineer", "Quality Assurance", 2.8, 22),
        ("Program Manager", "Project Management", 3.36, 27),
    ]),

    "CRM Development": _pkg("CRM Development", 1, [
        ("CRM Consultant", "Campaign Execution", 2, 16),
        ("CRM Developer", "Email Development", 10, 80),
        ("Program Manager", "Program Manager", 2.4, 19),
    ]),

    "CRM Development - light game": _pkg("CRM Development - light game", 1, [
        ("CRM Consultant", "Campaign Execution", 2, 16),
        ("CRM Developer", "Game Development", 2, 16),
        ("Program Manager", "Program Manager", 0.8, 6),
    ], notes="Single in-app game, no campaigns."),

    "CRM Development - 1st Game": _pkg("CRM Development - 1st Game", 1, [
        ("CRM Consultant", "Campaign Execution", 4, 32),
        ("CRM Developer", "Game Development", 5, 40),
        ("Program Manager", "Program Manager", 1.8, 14),
    ], notes="Game embedded into lifecycle campaigns."),

    "CRM Development - 3 Games": _pkg("CRM Development - 3 Games", 3, [
        ("CRM Consultant", "Campaign Execution", 2, 16),
        ("CRM Developer", "Game Development", 4.5, 36),
        ("Program Manager", "Program Manager", 1.3, 10),
    ]),

    "Braze SDK Advisory": _pkg("Braze SDK Advisory", 2, [
        ("CRM Consultant", "Data planning", 3, 24),
        ("Engineer", "Integration Advisory", 5, 40),
        ("Engineer", "Quality Assurance", 3, 24),
        ("Program Manager", "Project Management", 2, 16),
    ]),

    "Web app - MVP": _pkg("Web app - MVP", 12, [
        ("Product Owner", "Product Management", 4, 32),
        ("UX/UI Designer", "Wireframes & Design", 4, 32),
        ("Engineer", "Development", 10, 80),
        ("Engineer", "Dev Ops", 4, 32),
        ("Engineer", "Quality Assurance", 4.4, 35),
        ("Program Manager", "Project Management", 5.28, 42),
    ]),

    "Mobile app - MVP": _pkg("Mobile app - MVP", 12, [
        ("Product Owner", "Product Management", 4, 32),
        ("UX/UI Designer", "Wireframes & Design", 4, 32),
        ("Engineer", "Development", 10, 80),
        ("Engineer", "Dev Ops", 4, 32),
        ("Engineer", "Quality Assurance", 4.4, 35),
        ("Program Manager", "Project Management", 5.28, 42),
    ]),

    "Support & Maintenance": _pkg("Support & Maintenance", 1, [
        ("Product Owner", "Product Management", 4, 32),
        ("UX/UI Designer", "Wireframes & Design", 4, 32),
        ("Engineer", "Support & Maintenance", 10, 80),
        ("Engineer", "Quality Assurance", 3.6, 29),
        ("Program Manager", "Project Management", 4.32, 35),
    ]),

    # PLO variants
    "PLO - Lite": _pkg("PLO - Lite", 3, [
        ("Onboarding Consultant", "Onboarding", 2, 16),
    ]),
    "PLO - Growth": _pkg("PLO - Growth", 2, [
        ("Onboarding Consultant", "Onboarding", 4.5, 36),
    ]),
    "PLO - Growth - Bronze": _pkg("PLO - Growth - Bronze", 3, [
        ("Onboarding Consultant", "Onboarding", 2.2, 18),
    ]),
    "PLO - Growth - Silver": _pkg("PLO - Growth - Silver", 3, [
        ("Onboarding Consultant", "Onboarding", 2.5, 20),
        ("Technical Architect", "Technical Advisory", 2, 16),
    ]),
    "PLO - Quick Start": _pkg("PLO - Quick Start", 5, [
        ("Onboarding Consultant", "Onboarding", 5, 40),
        ("Technical Architect", "Technical Advisory", 1.5, 12),
    ]),
    "PLO - Ignite": _pkg("PLO - Ignite", 7, [
        ("Onboarding Consultant", "Onboarding", 5.5, 44),
        ("Technical Architect", "Technical Advisory", 1.5, 12),
    ]),
    "PLO - Custom": _pkg("PLO - Custom", 3, [
        ("Onboarding Consultant", "Onboarding", 4, 32),
        ("Technical Architect", "Technical Advisory", 2.75, 22),
    ]),

    # Small Market variants
    "Small Market - PLO": _pkg("Small Market - PLO", 3, [
        ("Onboarding Consultant", "Onboarding", 2, 16),
    ]),
    "Small Market - Vendor Exception": _pkg("Small Market - Vendor Exception", 1, [
        ("Consultant", "Business Case", 4.5, 36),
        ("Program Manager", "Project Plan", 0.9, 7),
    ]),
    "Small Market - Ongoing Operations": _pkg("Small Market - Ongoing Operations", 1, [
        ("CRM Consultant", "Campaign Planning", 0.2, 2),
        ("CRM Consultant", "Campaign Execution", 1.5, 12),
        ("CRM Consultant", "Quality Assurance", 0.17, 1),
        ("Program Manager", "Project Management", 0.374, 3),
    ]),

    # Add-ons / top-ups
    "PLO - add-on (Top-up)": _pkg("PLO - add-on (Top-up)", 1, [
        ("Onboarding Consultant", "Add-on (Top-up)", 5, 40),
    ]),
    "1 Journey - add-on (Top-up)": _pkg("1 Journey - add-on (Top-up)", 1, [
        ("CRM Developer", "Add-on (Top-up)", 7, 56),
    ]),
    "7 Journeys - Light": _pkg("7 Journeys - Light", 3, [
        ("CRM Developer", "Add-on (Top-up)", 6.5, 52),
    ], notes="Single Template, Single Channel Journeys."),
    "7 Journeys - Advanced": _pkg("7 Journeys - Advanced", 6, [
        ("CRM Developer", "Add-on (Top-up)", 6, 48),
        ("Program Manager", "Project Management", 1.2, 10),
    ], notes="Multi-channel Journeys, advanced designs."),
    "Small Market - 7 Journeys": _pkg("Small Market - 7 Journeys", 3, [
        ("CRM Developer", "Add-on (Top-up)", 2.24, 18),
    ]),
}


def list_packages() -> list[dict[str, Any]]:
    """Return packages as a list for the UI picker, sorted by name."""
    rows = [{"key": k, **v} for k, v in PACKAGES.items()]
    rows.sort(key=lambda r: r["name"])
    return rows


def get_package(key: str) -> dict[str, Any] | None:
    return PACKAGES.get(key)
