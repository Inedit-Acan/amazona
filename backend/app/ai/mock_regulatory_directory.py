"""Deterministic, fixture-driven regulatory/compliance directory by
category x market. No network access, no real legal research — this is
a stand-in for a future real regulatory-intelligence source, used only
to give the Legal Compliance agent (Fase 3, Agent 4) something to
analyze. Not legal advice; the fixture data below is invented for
demo purposes and does not reflect real, current regulations.
"""

_REGULATORY_DATASET: dict[str, dict[str, dict]] = {
    "electronics": {
        "us": {
            "restricted": False,
            "required_certifications": ["FCC"],
            "known_risks": ["battery shipping restrictions for lithium cells"],
            "recent_changes": [
                {
                    "date": "2026-06-01",
                    "description": "simulated: updated FCC labeling requirement for wireless devices",
                }
            ],
        },
        "eu": {
            "restricted": False,
            "required_certifications": ["CE", "RoHS"],
            "known_risks": ["WEEE take-back obligation for electronic waste"],
            "recent_changes": [
                {
                    "date": "2026-03-15",
                    "description": "simulated: EU RoHS scope update for wireless accessories",
                }
            ],
        },
        "mx": {
            "restricted": False,
            "required_certifications": ["NOM"],
            "known_risks": ["import permit required for wireless transmitters"],
            "recent_changes": [],
        },
    },
    "home": {
        "us": {
            "restricted": False,
            "required_certifications": [],
            "known_risks": ["CPSIA lead content limits apply if marketed for children"],
            "recent_changes": [],
        },
        "eu": {
            "restricted": False,
            "required_certifications": ["CE"],
            "known_risks": [],
            "recent_changes": [],
        },
        "mx": {
            "restricted": False,
            "required_certifications": ["NOM"],
            "known_risks": [],
            "recent_changes": [],
        },
    },
    "accessories": {
        "us": {
            "restricted": False,
            "required_certifications": [],
            "known_risks": [],
            "recent_changes": [],
        },
        "eu": {
            "restricted": True,
            "required_certifications": ["REACH"],
            "known_risks": ["restricted substances (e.g. certain phthalates) in synthetic leather/PVC"],
            "recent_changes": [
                {
                    "date": "2026-05-01",
                    "description": "simulated: REACH restriction added for certain phthalates in accessories",
                }
            ],
        },
        "mx": {
            "restricted": False,
            "required_certifications": [],
            "known_risks": [],
            "recent_changes": [],
        },
    },
}


class MockRegulatoryDirectory:
    """V1 stand-in for a real regulatory-intelligence source.
    Deterministic: the same (category, market) always returns the same
    result (or None for an unmodeled combination)."""

    def get_requirements(self, *, category: str, market: str) -> dict | None:
        return _REGULATORY_DATASET.get(category.lower(), {}).get(market.lower())
