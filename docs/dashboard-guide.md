# Traject Dashboard Guide

The Traject React dashboard is a purpose-built, self-hosted UI for teams operating AI inference
workloads in production. It ships as part of the Traject Phase 4 platform.

---

## Dashboard vs Grafana

Traject includes two observability UIs with different purposes:

| | Traject Dashboard | Grafana |
|---|---|---|
| **Primary audience** | Engineering leads, platform teams | DevOps, SREs |
| **Focus** | Cost attribution, budget management, router analytics | Infrastructure metrics, alerting, log correlation |
| **Data source** | Traject backend REST API (`/v1/attribution`, `/v1/spans`, `/v1/budgets`) | Prometheus, Loki, Postgres (direct) |
| **Auth** | Traject API key (`X-Traject-API-Key`) | Grafana native auth |
| **Port** | 5173 (dev) / 80 (Docker) | 3000 |
| **Tech** | React 18 + Vite + Recharts + Tailwind | Grafana OSS |

Use Grafana for infrastructure-level observability (latency percentiles, error rates, container
health). Use the Traject dashboard for business-level questions: which features cost the most,
which models are being routed, whether compression is saving tokens, and whether budgets are
near their limits.

---

## Running the Dashboard

### Via Docker Compose (recommended)

The dashboard service is included in `deploy/docker-compose.yml` and starts automatically:

```bash
git clone https://github.com/aarohimathur/traject
cd traject
cp deploy/.env.example deploy/.env
# Edit deploy/.env — set AXON_API_KEY and VITE_AXON_API_KEY
docker compose -f deploy/docker-compose.yml up -d
```

The dashboard is available at **http://localhost:5173** once the `traject-dashboard` container is
healthy. It depends on `traject-backend` being healthy first; Docker Compose enforces this ordering.

### Standalone (development)

Requires Node.js 20+:

```bash
cd dashboard
npm install
npm run dev
```

The dev server starts at **http://localhost:5173** with hot-module replacement enabled.

To point it at a remote backend:

```bash
VITE_AXON_BACKEND_URL=https://traject.internal.example.com \
VITE_AXON_API_KEY=traject_live_your_key_here \
npm run dev
```

### Production build (standalone nginx)

```bash
cd dashboard
npm run build         # outputs to dashboard/dist/
# Serve dist/ with any static file server or the included Dockerfile
docker build -t traject-dashboard .
docker run -p 5173:80 traject-dashboard
```

---

## Pages

### 1. Cost Overview (`/`)

**What it shows:** A high-level breakdown of all inference spend attributed through the Traject SDK.

- **4 stat cards** — total cost (USD), total tokens consumed, cache hit rate (%), and tokens saved
  by compression.
- **Cost over time chart** — line chart grouped by `feature_tag`, showing spend trends across the
  selected time range (24h / 7d / 30d).
- **Model breakdown** — bar chart showing cost share per model (`gpt-4o`, `claude-3-5-sonnet`, etc.).
- **Provider breakdown** — donut chart showing OpenAI vs Anthropic vs other provider split.
- **Top feature tags table** — sortable table of the 10 most expensive `feature_tag` values with
  cost, tokens, and cache hit rate columns.

**Expected data:** Populated as soon as the SDK is instrumented and spans are flowing to the
backend. The time-range selector in the header controls all panels on the page.

---

### 2. Compression ROI (`/compression`)

**What it shows:** The economic value of trajectory compression in aggregate and per feature.

- **4 stat cards** — total tokens saved, estimated cost saved (USD), average compression ratio,
  and shadow vs live split (how many spans are still in shadow mode).
- **Tokens saved over time** — area chart showing cumulative compression savings by day.
- **Compression ratio by feature** — horizontal bar chart ranking feature tags by their average
  compression ratio (higher = more aggressive compression achieved).
- **Cache hit rate over time** — line chart showing semantic cache effectiveness.
- **Cumulative cost saved** — running total of cost avoided since instrumentation began.

**Expected data:** Only spans with `compression_applied=true` contribute to compression metrics.
Shadow-mode spans show as savings opportunities but are counted separately.

---

### 3. Budget Manager (`/budgets`)

**What it shows:** Current budget utilization and controls for all active feature-tag budgets.

- **Budget table** — one row per budget; columns: feature tag, budget limit (USD/period),
  current spend, utilization %, status badge, actions.
- **Status badges:**
  - `text-green-400` — under 80% utilized
  - `text-yellow-400` — 80–99% utilized
  - `text-red-400` — at or over 100% (budget exhausted)
- **Add / edit form** — inline form below the table header; no modal; submit calls
  `PUT /v1/budgets/{feature_tag}`.
- **Delete confirmation** — inline confirmation in the table row; calls
  `DELETE /v1/budgets/{feature_tag}`.
- **Budget gauges** — one `RadialBarChart` gauge per feature tag rendered below the table,
  color-matched to status.

**Expected data:** Budget rows appear after at least one budget has been created via the
`POST /v1/budgets` API or the inline form.

---

### 4. Router Analytics (`/router`)

**What it shows:** Decisions made by the Traject adaptive model router and their cost impact.

- **Routing decisions table** — sortable; columns: timestamp, original model requested,
  selected (routed) model, task type, complexity tier, cost delta % vs original.
- **Model distribution donut** — share of routed traffic across all selected models.
- **Cumulative savings stat card** — total cost delta saved by routing to cheaper models.
- **Task type breakdown bar chart** — volume of routing decisions grouped by `task_type`
  (e.g., `code_generation`, `summarization`, `qa`).

**Expected data:** Populated only when the SDK router is active (`traject.patch(client, router=True)`)
and routing decisions are flowing. Spans with `routing_decision=null` are baseline (unrouted)
calls and are excluded from this page.

---

### 5. Span Explorer (`/spans`)

**What it shows:** Raw inference span records with full filter and pagination controls.

- **Filter bar** — dropdowns and inputs for: `feature_tag`, `model`, `provider`, `environment`,
  date range start/end, `compression_applied` (yes / no / all).
- **Span table** — 50 rows per page; expandable rows reveal: `prompt_hash` (SHA-256),
  `artifact_type`, `routing_decision`, `tokens_saved`, `batch_eligible`.
- **Pagination controls** — previous / next page; total count displayed.

**Expected data:** Every instrumented LLM call produces one span row. Filter by `feature_tag`
to focus on a specific agent or workflow. Expand a row to see the compression and routing
details for that individual call.

---

## Configuration

The dashboard reads two environment variables at build time (Vite inlines them as static values
in the compiled JS bundle):

| Variable | Default | Description |
|---|---|---|
| `VITE_AXON_BACKEND_URL` | `http://localhost:8000` | Base URL of the Traject backend API. Set to your backend's public or internal URL in production. |
| `VITE_AXON_API_KEY` | _(none)_ | API key sent as `X-Traject-API-Key` on every request. Must have at minimum `viewer` role to read data. Use an `engineer` or `admin` key to manage budgets. |

### Setting variables in Docker Compose

Edit `deploy/.env`:

```dotenv
VITE_AXON_BACKEND_URL=http://traject-backend:8000
VITE_AXON_API_KEY=traject_live_your_key_here
```

The `traject-dashboard` service in `docker-compose.yml` picks these up automatically.

### Setting variables for a standalone build

Pass them at `npm run build` time:

```bash
VITE_AXON_BACKEND_URL=https://traject.internal.example.com \
VITE_AXON_API_KEY=traject_live_your_key_here \
npm run build
```

Because Vite inlines environment variables at build time, the compiled `dist/` bundle is
environment-specific. Build separate bundles for staging and production, or use a runtime
configuration approach (environment-specific nginx proxy + build-time placeholder replacement).

> **Security note:** `VITE_AXON_API_KEY` is embedded in the JavaScript bundle and visible in
> the browser. Use a `viewer`-role key for the dashboard in environments where the bundle is
> accessible to untrusted users. Admin operations should go through the backend API directly.
