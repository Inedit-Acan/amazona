"""Deterministic, fixture-driven ad performance estimates by category x
platform. No network access, no real Meta/Google/TikTok Ads API
credentials or calls. Every estimate is tagged
data_origin="simulated_ad_performance_estimate" so it is never mistaken
for real ad-platform reporting data.
"""

_AD_PERFORMANCE_DATASET: dict[str, dict[str, dict]] = {
    "electronics": {
        "meta": {"avg_cpc": 0.85, "avg_ctr": 0.012, "conversion_rate": 0.02},
        "google": {"avg_cpc": 1.10, "avg_ctr": 0.035, "conversion_rate": 0.03},
    },
    "home": {
        "meta": {"avg_cpc": 0.55, "avg_ctr": 0.015, "conversion_rate": 0.025},
        "google": {"avg_cpc": 0.70, "avg_ctr": 0.03, "conversion_rate": 0.028},
    },
    "accessories": {
        "meta": {"avg_cpc": 0.40, "avg_ctr": 0.018, "conversion_rate": 0.02},
        "google": {"avg_cpc": 0.60, "avg_ctr": 0.025, "conversion_rate": 0.022},
    },
}
_DATA_ORIGIN = "simulated_ad_performance_estimate"


class MockAdPerformanceDirectory:
    """V1 stand-in for a real ad-platform reporting API. Deterministic:
    the same (category, platform) always returns the same result (or
    None for an unmodeled combination)."""

    def get_performance_estimate(self, *, category: str, platform: str) -> dict | None:
        base = _AD_PERFORMANCE_DATASET.get(category.lower(), {}).get(platform.lower())
        if base is None:
            return None
        return {**base, "data_origin": _DATA_ORIGIN}
