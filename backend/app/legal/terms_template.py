"""Deterministic terms & conditions boilerplate generator. Produces a
draft template only — not a real legal document, and not legal advice.
A human (or real counsel) must review and adapt it before any real use.
"""


def generate_terms_and_conditions(*, category: str, market: str, product_name: str) -> str:
    return (
        f"DRAFT TEMPLATE — Terms and Conditions for {product_name} ({category}, market: {market})\n\n"
        f"1. Scope. These terms apply to the sale of {product_name} in the {market} market.\n"
        f"2. Product category. This item is classified under {category} for regulatory purposes.\n"
        "3. Warranty. Simulated placeholder clause — replace with the seller's actual warranty terms.\n"
        "4. Returns. Simulated placeholder clause — replace with the seller's actual returns policy.\n"
        "5. Liability. Simulated placeholder clause — replace with jurisdiction-appropriate liability limits.\n\n"
        "This document is an auto-generated draft template for internal review only. "
        "It is not legal advice and must not be published or relied upon without review by qualified counsel."
    )
