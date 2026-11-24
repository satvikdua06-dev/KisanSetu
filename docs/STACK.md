# KisanSetu tech stack (decision record)

**Status:** decided, 2026-11-24. Change it only by editing this file with the reason.

## Goals that drove the choices

1. **One codebase for Android, iOS and web.** The farmer app must ship to Android first (most of our users), then iOS, without a rewrite.
2. **Scale without re-architecture.** Start as one deployable backend, grow by adding workers and replicas, split services only when load proves it.
3. **The LLM only does language and planning.** Prices, costs, matching and routing stay in deterministic, testable code (as the README promises).
4. **Works on low-end phones and bad networks.** Offline-first farmer app, SMS/voice-call fallback.
5. **Farmer data stays in India.** Hosting in an Indian region, consent before sharing, auditable records.

## The stack

### Clients

| Concern | Choice | Why |
|---|---|---|
| Farmer app (Android, iOS, web) | **Expo (React Native) + Expo Router, TypeScript** | One codebase builds a native Android app, a native iOS app and a web app. "Moving to iOS" is a build target, not a port. |
| FPO, buyer and transporter dashboards | **Next.js (App Router), TypeScript** | Data-heavy desktop screens, server rendering, easy hosting. Shares packages with the mobile app. |
| Styling | **NativeWind (Tailwind for React Native) + Tailwind** | Same design tokens and class names on mobile and web. |
| Server state and caching | **TanStack Query** | Same data-fetching code on mobile and web; retries and offline persistence. |
| Offline | **expo-sqlite + a queued-mutation outbox** | Harvest registration and approvals work without signal and sync later. |
| Push notifications | **Expo Notifications (FCM on Android, APNs on iOS)** | One API for both platforms. |
| Mobile builds and updates | **EAS Build + EAS Update** | Play Store / App Store builds from CI, over-the-air fixes for JS changes. |

### Shared code (monorepo)

**pnpm workspaces + Turborepo.** The API contract is the bridge between clients and backend:

- FastAPI publishes an **OpenAPI** schema.
- `packages/api-client` is **generated** from it (openapi-typescript + openapi-fetch), so mobile and web always call the backend with the same typed client.
- `packages/i18n` holds UI strings for every supported language, shared by both apps.
- `packages/ui-tokens` holds colours, spacing and typography for NativeWind and Tailwind.

### Backend

| Concern | Choice | Why |
|---|---|---|
| Language and API | **Python 3.12, FastAPI, Pydantic v2** | Python has the optimisation, data and AI libraries we need; FastAPI gives async I/O and an OpenAPI contract for free. |
| Packaging | **uv** | Fast, reproducible installs and lockfile. |
| Database | **PostgreSQL 16 + PostGIS** | Relational core (farmers, lots, orders, approvals, settlements) plus geospatial queries for "farmers within X km" and pickup routing. |
| ORM and migrations | **SQLAlchemy 2 (async) + Alembic** | Mature, typed, versioned schema changes. |
| Cache, queues, rate limits | **Redis 7** | One piece of infra for caching and job queues. |
| Background jobs | **ARQ (async workers on Redis)** | Agent runs, price ingestion, notifications and replanning run outside the request path. Workers scale independently of the API. |
| Workflow state | **Postgres tables we own** (workflow, step, approval, event) + a transactional outbox | Selling workflows last days and wait on human approvals; the state must be durable, queryable and auditable, not held in an LLM context. |
| Optimisation | **Google OR-Tools** | CP-SAT for matching and aggregation constraints, routing solver for pickups and vehicle loads. |
| Auth | **Phone number + OTP, JWT access tokens, role-based access in Postgres** (farmer, FPO coordinator, buyer, transporter, admin) | Farmers don't use email or passwords. Every query is scoped to the caller's FPO or organisation. |

### AI layer

| Concern | Choice |
|---|---|
| Orchestrator (planning, tool selection, exceptions, replanning) | **Claude Opus 5.5** (`claude-opus-5-5`) via the official `anthropic` Python SDK, with tool use and adaptive thinking. |
| High-volume, simple calls (intent parsing of transcribed speech, slot filling, short replies) | **Claude Haiku 5.5** (`claude-haiku-5-5`). |
| How agents run | The seven agents are **tools and sub-steps the orchestrator calls**; the loop runs in our ARQ workers, and every step reads and writes the Postgres workflow state. Human approval is a workflow state, never something the model can skip. |

We host the agent loop ourselves (Claude API + tool use) rather than using Anthropic's hosted Managed Agents, because the workflow must pause for days on farmer approvals, persist in our database, and sit next to our deterministic tools. This can be revisited.

### Voice, messaging and external data

| Concern | Choice |
|---|---|
| Speech-to-text and text-to-speech in Indian languages | Behind a `speech` adapter. Candidates: **Bhashini** (Government of India language platform) and **Sarvam AI**. Choose after testing both on the prototype region's language (Gujarati for the tomato scenario). |
| SMS, voice-call (IVR) fallback, OTP | Behind a `messaging` adapter. Candidates: **Exotel** or **Twilio**. |
| Mandi prices and arrivals | **Agmarknet data through the data.gov.in open-data API**, ingested daily into Postgres with source and date on every row. Verify the dataset and access terms before building the ingester. |
| Distances and routes | **OSRM on OpenStreetMap India data** (self-hosted, no per-call cost). |
| Simulated data | Buyer requirements, transporter availability, storage and payment confirmation are **seeded simulations**, tagged `simulated` in the database and shown as such in the UI. |

Every external provider sits behind an adapter interface, so swapping one is a config change, not a rewrite.

### Infrastructure

| Concern | Choice |
|---|---|
| Local development | **Docker Compose**: API, worker, Postgres+PostGIS, Redis, OSRM. |
| Prototype hosting | Containers on any managed container host; managed Postgres. |
| Production | **AWS Mumbai (ap-south-1)**: ECS Fargate (API and workers), RDS PostgreSQL, ElastiCache Redis, S3 for audio and documents. Keeps farmer data in India for the Digital Personal Data Protection Act. |
| CI/CD | **GitHub Actions** (lint, test, build, migrate) + EAS for mobile. |
| Monitoring | **Sentry** (errors, mobile and backend) + **OpenTelemetry** traces. |
| Testing | pytest (backend), Vitest (TypeScript packages), Maestro (mobile flows), Playwright (dashboards). |

## Repository layout

```
apps/
  mobile/            Expo app: farmer (Android, iOS, web)
  web/               Next.js: FPO, buyer, transporter dashboards
services/
  api/               FastAPI app, domain modules, ARQ workers, Alembic migrations
    app/agents/      orchestrator + seven agents (tools around deterministic code)
    app/domain/      farmers, harvests, markets, buyers, lots, logistics, transactions
    app/adapters/    speech, messaging, market data, maps
packages/
  api-client/        generated from the API's OpenAPI schema
  i18n/              UI strings for every supported language
  ui-tokens/         shared design tokens
infra/               Docker Compose, deployment config
docs/
```

## How it scales

- **Stage 1 (prototype, one district):** one API container, one worker, one Postgres, one Redis.
- **Stage 2 (several FPOs and districts):** run more API and worker containers behind a load balancer (both are stateless), add a Postgres read replica for dashboards and reports, cache price queries in Redis.
- **Stage 3 (regional network):** split the busiest domain modules (for example market data ingestion or notifications) into their own services. The modules already talk through the outbox events, so the split is mechanical. Partition large tables by region and season.

## Options considered and rejected

| Option | Why not |
|---|---|
| Flutter | Good for mobile, but our dashboards would be a separate TypeScript codebase with nothing shared. Expo + Next.js shares one language, one API client and one set of strings. |
| Separate native Kotlin and Swift apps | Two codebases to build and keep in step; too slow for a small team. |
| Web-only PWA | Weaker offline storage, background sync and push on iOS, and no store presence. Expo still gives us a web build. |
| Node.js backend | The optimisation (OR-Tools), data and AI tooling we need is strongest in Python. |
| An LLM agent framework holding the workflow state | Selling workflows wait days on approvals and need audit trails; we keep the state in our own Postgres tables and call Claude per step. |
| Microservices from day one | Adds network and deployment cost before we have the load to justify it. Modular monolith first. |
