# Milestone 1 Demo

This walks through the complete simulated product-validation flow from a
clean environment: no real money, orders, suppliers, or tax submissions.

## 1. Local setup

```bash
# Infrastructure (PostgreSQL + Redis) — optional for this demo, see note below
docker compose -f infra/docker-compose.yml up -d

# Backend
cd backend
python -m venv .venv
.venv/Scripts/activate       # Windows; `source .venv/bin/activate` on Unix
pip install -e ".[dev]"
alembic upgrade head          # requires DATABASE_URL to point at a real Postgres,
                               # or set DATABASE_URL=sqlite:///demo.db for a quick local demo
uvicorn app.main:app --reload

# Control Center (separate shell)
cd apps/control-center
npm install
npm run dev
```

Open http://localhost:3000 — it redirects to the Dashboard.

## 2. Automated verification

```bash
cd backend
pytest                                  # full suite: unit + integration + e2e
pytest tests/e2e -v                     # just the three Milestone 1 scenarios below
```

```bash
cd apps/control-center
npm run lint
npx tsc --noEmit
npm test                                # approval expiry/actionability logic
npm run build
```

## 3. Driving one objective through the API

```bash
curl -s -X POST http://localhost:8000/api/objectives \
  -H "Content-Type: application/json" \
  -d '{
    "title": "Validate wireless earbuds opportunity",
    "created_by": "owner@amazona.local",
    "context": {
      "product_validation": {"estimated_monthly_searches": 12000, "competition_level": "low"},
      "supplier_sourcing": {"unit_cost": 5.0, "lead_time_days": 20, "supplier_verified": true},
      "finance_validation": {"unit_cost": 5.0, "sale_price": 20.0, "monthly_unit_sales": 300, "monthly_fixed_costs": 500.0},
      "legal_validation": {"restricted_category": false},
      "requests_simulated_spend": true,
      "spend_action": "launch_marketing_campaign",
      "spend_amount": 150.0
    }
  }'
# -> {"id": "<objective_id>", ...}

curl -s -X POST http://localhost:8000/api/objectives/<objective_id>/run
# -> {"id": "<decision_id>", "project_id": "...", "status": "HUMAN_APPROVAL", ...}
```

Or use the Control Center: **CEO** page -> fill in title/context -> *Create & run
objective* -> redirected straight to the project detail page with the task
graph and CEO decision.

## 4. The three Milestone 1 scenarios

Covered by `backend/tests/e2e/test_product_validation_flow.py`, and
reproducible by hand via the API or the CEO page's context editor.

### Scenario A — Human approval

Product attractive, supplier viable, finance profitable, legal clear, and a
simulated marketing spend requested.

- **Result:** `HUMAN_APPROVAL`
- One `PENDING` approval is created for the requested spend.
- Review and resolve it on the **Approvals** page (desktop or mobile) —
  Approve/Reject, with full agent evidence under *More information*.

### Scenario B — Legal veto

Same product, but Legal is `BLOCKED` (a restricted category without the
required certification).

- **Result:** `NO_GO`
- **No approval is created**, even though a spend was requested — a veto
  always wins over a human-approval request.
- Project status becomes `REJECTED`.

To reproduce: set `legal_validation` to
`{"restricted_category": true, "requires_certification": true, "certification_available": false}`.

### Scenario C — Insufficient confidence

Weak/missing product data (e.g. no `estimated_monthly_searches` or
`competition_level`).

- **Result:** `REVIEW`
- The Product agent's low confidence drags the CEO's aggregated confidence
  below the GO threshold, regardless of the other agents or any requested
  spend.

To reproduce: set `product_validation` to just `{"product_name": "Unknown gadget"}`.

## 5. Tracing one run end to end

Every run returns a `correlation_id`. Use it to pull the full audit trail:

```bash
curl -s "http://localhost:8000/api/audit?correlation_id=<correlation_id>"
```

Or open **Audit** in the Control Center — the project detail page links
straight to the filtered trail for its decision.

## 6. What is *not* real in Milestone 1

- No real payment, ad platform, supplier, or tax integration of any kind.
- The four specialist agents are deterministic, fixture-driven simulations
  (no live web/search access).
- The AI Gateway's only provider is a mock that never calls a real model.
- Budget/permission checks are enforced, but all amounts are simulated.
