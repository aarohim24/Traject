# Deploying a public live demo (Render + Vercel)

This gives anyone a clickable URL that shows real dashboards populated with
real data — no cloning, no Docker, no bringing your own LLM traffic. Nothing
here has been deployed or tested against a live Render/Vercel account from
this environment (no account access) — follow it step by step and adjust if
Render/Vercel's UI has moved since this was written.

## 1. Backend — Render

1. Push this repo to GitHub if it isn't already.
2. In the Render dashboard: **New +** → **Blueprint**, point it at the repo.
   Render reads `render.yaml` at the repo root and provisions: a Postgres
   database, a Redis instance, and the backend web service (Docker build
   from `backend/Dockerfile`).
3. **Known gotcha, must fix manually after first deploy**: Render's Postgres
   connection string uses `postgresql://`, but the backend's async SQLAlchemy
   engine requires `postgresql+asyncpg://`. After the blueprint deploys, go to
   the `traject-demo-backend` service → Environment → `DATABASE_URL`, and
   prepend `+asyncpg` right after `postgresql` in the value. Redeploy.
4. **Confirm pgvector is available** on whatever Postgres plan you pick —
   older/free tiers on some providers don't include it. If migrations fail
   on `CREATE EXTENSION vector`, you'll need a plan that supports it.
5. Once healthy, hit `https://<your-service>.onrender.com/health` — should
   return `{"status": "ok"}` (see `backend/traject_backend/main.py`).
6. Copy the auto-generated `API_KEY` value from the service's environment
   tab — you'll need it for both seeding and the dashboard.

## 2. Seed it with real data

This populates Cost Overview, Compression ROI, Span Explorer, Budget
Manager, and Benchmark Registry with data derived from actually running
Traject's compression engine against the real public SWE-bench trajectories
already in this repo (`swe_trajectories.jsonl`) — not fabricated numbers.
See `backend/scripts/seed_demo_data.py`'s module docstring for exactly what's
real vs. a disclosed display choice (model/feature-tag labels).

```bash
pip install -e "sdk/python[dev]"
python backend/scripts/seed_demo_data.py \
  --backend-url https://<your-service>.onrender.com \
  --api-key <the API_KEY from step 1.6>
```

## 3. Dashboard — Vercel

1. In Vercel: **Add New** → **Project**, import this repo, set **Root
   Directory** to `dashboard/`. `dashboard/vercel.json` handles the build
   command, output directory, and SPA routing fallback.
2. Set two environment variables in the Vercel project settings:
   - `VITE_TRAJECT_BACKEND_URL` = `https://<your-render-service>.onrender.com`
   - `VITE_TRAJECT_API_KEY` = the same API key from step 1.6
3. **Security note**: Vite bundles `VITE_*` env vars into the public
   client-side JS — anyone can view-source and read this key. That's fine
   *only* because this is a dedicated, low-stakes demo instance seeded with
   public benchmark data (no real prompt content is ever stored per
   ADR-005) — never reuse a real production API key here.
4. Deploy. Then go back to Render and update `CORS_ORIGINS` on the backend
   service to your actual Vercel URL (`render.yaml` ships a placeholder).

## 4. Sanity check before sharing the link

- Open the deployed dashboard URL, click through all 6 pages, confirm each
  shows non-empty data.
- Open `https://<backend>/health`, `/health/db`, `/health/redis` — all three
  should be healthy.
- Consider adding a small "sample data from the public SWE-Gym benchmark"
  banner to the dashboard so it's clear this isn't live production traffic
  — disclosure, not spin.
