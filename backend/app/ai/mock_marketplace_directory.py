"""Deterministic, fixture-driven marketplace directory by category x
platform. No network access, no real marketplace-seller-API data.

Project-wide policy (see README.md "Notas"): Amazon SP-API data must
never be used to train models. This module never calls SP-API — it is
a fully simulated stand-in — but because its shape resembles what a
real SP-API integration would eventually return (competitor pricing,
category commissions, platform policy), every competition block is
explicitly tagged `data_origin="simulated_not_sp_api"` and lives in
this isolated module, so it can never be mistaken for real SP-API
output now or if a real integration is added later.

Only "amazon" is modeled today. Other platforms ("y otros" in the
milestone's scope) are supported by the input schema but simply return
None (unmodeled) until fixture data is added for them.
"""

_MARKETPLACE_DATASET: dict[str, dict[str, dict]] = {
    "electronics": {
        "amazon": {
            "competition": {
                "competitor_count": 120,
                "avg_price": 22.5,
                "avg_rating": 4.2,
                "buy_box_difficulty": "high",
                "data_origin": "simulated_not_sp_api",
            },
            "commission": {"referral_fee_percent": 0.08, "fulfillment_fee_per_unit": 3.5},
            "policy": {
                "approval_required": True,
                "prohibited": False,
                "notes": ["requires Amazon category approval for wireless electronics"],
            },
        }
    },
    "home": {
        "amazon": {
            "competition": {
                "competitor_count": 80,
                "avg_price": 18.0,
                "avg_rating": 4.4,
                "buy_box_difficulty": "medium",
                "data_origin": "simulated_not_sp_api",
            },
            "commission": {"referral_fee_percent": 0.15, "fulfillment_fee_per_unit": 4.0},
            "policy": {"approval_required": False, "prohibited": False, "notes": []},
        }
    },
    "accessories": {
        "amazon": {
            "competition": {
                "competitor_count": 200,
                "avg_price": 12.0,
                "avg_rating": 4.0,
                "buy_box_difficulty": "high",
                "data_origin": "simulated_not_sp_api",
            },
            "commission": {"referral_fee_percent": 0.15, "fulfillment_fee_per_unit": 2.8},
            "policy": {"approval_required": False, "prohibited": False, "notes": []},
        }
    },
}


class MockMarketplaceDirectory:
    """V1 stand-in for a real marketplace-seller-API source. Deterministic:
    the same (category, platform) always returns the same result (or
    None for an unmodeled combination)."""

    def get_marketplace_data(self, *, category: str, platform: str) -> dict | None:
        return _MARKETPLACE_DATASET.get(category.lower(), {}).get(platform.lower())
