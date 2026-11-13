# KisanSetu

**An agentic AI-powered agricultural market access and intelligent selling network.**

Tech4Bharat 2026 · Agriculture and Food Processing · Problem Statement 6.1: *Farmers sell at the wrong time, place and price.*

> **Status: proposed architecture and prototype workflow.** Nothing here is a deployed product. There are no onboarded farmers, buyers or partners, and no measured impact results. Any market price, buyer demand or offer in the prototype is labelled as observed, historical, forecast or simulated, with its source and date.

## The problem

Small and marginal farmers face six linked constraints when selling:

| Constraint | What it means |
|---|---|
| Information asymmetry | Net prices across markets are hard to see |
| Fragmented supply | Individual quantities are too small for larger buyers |
| Limited buyer access | Dependence on a few local buyers and intermediaries |
| Transport economics | A higher price can vanish after transport and handling |
| Time pressure | Perishable produce forces a quick sale |
| Transaction uncertainty | Disputes over quantity, deductions and payment |

Solving one alone rarely improves what the farmer finally earns. A better price at another mandi is no use without affordable transport and a buyer there.

## What exists today and where the gap is

Public price information already exists. [Agmarknet](https://agmarknet.gov.in) publishes daily mandi prices and arrivals by market and commodity, and [eNAM](https://enam.gov.in) is the government's electronic trading platform linking APMC mandis. Private marketplaces and advisory apps offer price feeds and buyer listings.

We do not claim these services are missing. Each stops at information or at a single step, and the farmer is left to connect price, buyer, quantity and transport alone. KisanSetu is the coordination layer on top: one workflow from registered harvest to reconciled payment, using existing public data wherever it is available.

## The approach

KisanSetu does not only tell farmers where prices are better. It helps them discover, evaluate, coordinate and execute a better sale, and the farmer approves every commitment.

A farmer reports, by voice and in their own language (directly or through their FPO coordinator), what they are growing, how much, when it will be ready and where they are. A central orchestrator then coordinates seven specialised agents over one shared record of the harvest.

| Agent | Responsibility |
|---|---|
| Crop and Harvest Intelligence | Crop, quantity, harvest dates, location; early surplus alerts when many farmers nearby expect the same crop in the same week |
| Market Intelligence | Prices, arrivals, trends, costs; net realisation as a range, never a single guaranteed figure |
| Buyer Matching | Matches farmer supply with published buyer requirements |
| Collective Selling | Pools compatible lots into viable quantities; compares collective vs individual sale per farmer |
| Logistics | Vehicle capacity, transport cost, pickups, shared loads |
| Storage Decision | Sell now versus store and sell later, with perishability, quality loss and price uncertainty |
| Transaction and Trust | Agreed terms, dispatch, delivery, payment status, receipts, discrepancies |

### Replanning

Replanning is the core of the agentic design. If a buyer withdraws, a transporter becomes unavailable or a farmer reports a smaller harvest, the orchestrator re-evaluates the remaining options, produces a revised proposal and asks the affected farmers to approve again. Nothing committed earlier changes without consent. This is the centrepiece of the prototype demonstration.

### What is AI and what is not

| Responsibility | Handled by |
|---|---|
| Intent understanding, natural-language interaction | LLM |
| Workflow planning, tool selection, exception handling, replanning | Agent orchestration |
| Price arithmetic, cost and net-realisation calculation | Deterministic code |
| Supply-demand matching, aggregation | Constraint-based algorithms |
| Logistics | Optimisation algorithms |
| Selling commitments, agreements, settlements | Human approval |

## Net realisation, not headline price

```
Net realisation per kg = expected price − transport − handling − market fees − expected quality deductions
```

Prices come from public mandi data where available, shown with their date so stale data is visible. Transport cost is computed from distance and vehicle capacity; other costs are supplied by the FPO or marked as assumptions. Estimates are shown as ranges.

Illustrative figures only:

| Selling option | Quoted ₹/kg | Costs ₹/kg | Net ₹/kg | Net for 1,000 kg |
|---|---:|---:|---:|---:|
| Local mandi | 20 | 1 | 19 | ₹19,000 |
| Regional mandi | 24 | 3 | 21 | ₹21,000 |
| Distant wholesale market | 27 | 6 | 21 | ₹21,000 |

The highest quoted price is not the highest earning.

## Illustrative workflow

A farmer in Gujarat expects 3,000 kg of tomatoes in five days.

1. **Harvest registration** by voice (Crop and Harvest agent)
2. **Market investigation** on net realisation (Market Intelligence agent)
3. **Buyer discovery**: a processor needs 5,000 kg in the window (Buyer Matching agent)
4. **Collective supply**: nearby farmers or an FPO for the other 2,000 kg (Collective Selling agent)
5. **Logistics planning**: one vehicle across the pickups (Logistics agent)
6. **Transaction proposal**: price, deductions, transport, expected proceeds (orchestrator)
7. **Human approval**: each farmer approves their own commitment
8. **Execution and reconciliation**: dispatch, delivered quantity, payment status (Transaction and Trust agent)

If the processor pulls out partway through, the orchestrator replans from what is left and asks the farmers again.

## Rules for collective selling

- Each farmer's lot is weighed, graded and recorded separately, even when sold together.
- Proceeds are split pro rata by the weight the buyer accepts in each grade, at that grade's price.
- Shared costs such as transport are split by weight carried.
- A shortfall reduces only that farmer's share and is handled by replanning, not passed to others.
- A rejected or downgraded lot affects only the farmer who supplied it.
- Every farmer sees their expected proceeds before approving and their own settlement summary afterwards.

## Entry strategy: FPO-first

A market-access network has a cold-start problem: buyers won't join without supply, and farmers won't join without buyers. We enter through Farmer Producer Organisations. An FPO already aggregates members, has a coordinator who can help farmers with low digital literacy, and can offer buyers a meaningful quantity from day one. The FPO is the first institutional customer and operates the collective-selling workflow.

## Prototype scope

One perishable crop in one district.

| Built as working software | Represented by labelled simulations |
|---|---|
| Voice harvest registration | Buyer requirements |
| Net-realisation comparison | Transporter availability |
| Buyer matching and aggregation | Storage facilities |
| Approval step and replanning | Payment confirmation |

## Proposed architecture

```
1  User experience        Farmer app (voice-first, multilingual) · FPO dashboard · buyer portal · transporter interface
2  Application services   Auth and roles · farmers and crops · buyers and procurement · orders · logistics and storage
3  Agent orchestration    Central orchestrator  <-- defined tools + shared state -->  7 specialised agents
4  Intelligence           LLM: language, planning, tool use  |  Algorithms: matching, net realisation, routing, forecasts
5  Data and integrations  Operational DB · persistent memory of orders, decisions, approvals · external data via APIs
```

Human approval gates sit outside the agents: selling commitments, negotiated agreements, collective participation, settlements. Market data comes from external systems, not from the model.

### Proposed stack

| Layer | Technology |
|---|---|
| Frontend | React / Next.js, mobile-first |
| Backend | Python FastAPI |
| Database | PostgreSQL |
| Orchestration | Stateful agent layer with tool calls, approvals, retries |
| AI | LLM for language understanding, planning, coordination |
| Optimisation | Deterministic and constraint-based algorithms |
| Voice | Speech-to-text and text-to-speech |
| Integrations | Market data, maps, notifications via supported APIs or labelled simulations |

## Accessibility and inclusion

Voice-first interaction in the farmer's language, audio confirmation of every commitment and simple screens. With low or intermittent connectivity, alerts and approvals fall back to SMS and voice calls, and FPO coordinators can act on a farmer's instruction with the farmer's confirmation recorded.

## Responsible use

- Recommendations are explained, with price uncertainty shown, and can be rejected.
- No guaranteed price-increase claims.
- Consent is required before sharing farmer location or financial data with buyers.
- Approval is required before any sale is committed.
- KisanSetu records payment status but does not hold or move farmers' money.
- Transactions keep an auditable record.

## How we would measure impact

Target metrics for future evaluation, not results, compared against a baseline for the same crop and season: change in net realisation per kg, farmers accessing new buyers, volume sold collectively, transport cost per kg, share of transactions completed, payment reconciliation time, farmer repeat usage.

## Roadmap

1. One crop, one district
2. Validate the workflow with farmers and an FPO
3. Onboard local buyers and transporters
4. Add crops and neighbouring markets
5. Extend through FPOs and institutional partnerships
6. Regional market-access networks

## Repository contents

| Path | Contents |
|---|---|
| `docs/KisanSetu_Pitch_Deck.pdf` | Pitch deck (PDF) |
| `docs/KisanSetu_Pitch_Deck.pptx` | Pitch deck (editable, with speaker notes) |
| `docs/KisanSetu_Speaker_Script_and_Sources.md` | Speaker script and sources |
| `docs/KisanSetu_Submission_Text.txt` | Submission text: brief and detailed explanation |

<!-- Add prototype code folders here as they land, and say for each data source whether it is live or simulated. -->
