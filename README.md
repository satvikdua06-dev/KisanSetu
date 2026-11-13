# KisanSetu

**An agentic AI-powered agricultural market access and intelligent selling network.**

Tech4Bharat 2026 · Agriculture and Food Processing · Problem Statement 6.1: *Farmers sell at the wrong time, place and price.*

> **Status: proposed architecture and prototype workflow.** Nothing here is a deployed product. There are no onboarded farmers, buyers or partners, and no measured impact results. Any market price, buyer demand or offer in the prototype is labelled as real, sourced or simulated.

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

## The approach

KisanSetu does not only tell farmers where prices are better. It helps them discover, evaluate, coordinate and execute a better sale, and the farmer approves every commitment.

A farmer reports, by voice and in their own language, what they are growing, how much, when it will be ready and where they are. A central orchestrator then coordinates seven specialised agents over one shared workflow state.

| Agent | Responsibility |
|---|---|
| Crop and Harvest Intelligence | Crop availability, harvest dates, quantities, location |
| Market Intelligence | Prices, arrivals, trends, costs, net realisation |
| Buyer Matching | Matches farmer supply with buyer procurement needs |
| Collective Selling | Aggregates small lots, evaluates group sales |
| Logistics | Vehicles, transport costs, pickup and delivery |
| Storage Decision | Sell now versus store and sell later |
| Transaction and Trust | Agreements, delivery records, payments, history |

The orchestrator understands the farmer's goal, keeps the workflow state, delegates tasks, evaluates results, handles exceptions, requests human approval and decides the next action.

### What is AI and what is not

| Responsibility | Handled by |
|---|---|
| Intent understanding, natural-language interaction | LLM |
| Workflow planning, tool selection, exception handling | Agent orchestration |
| Price arithmetic, cost and net-realisation calculation | Deterministic code |
| Supply-demand matching, aggregation | Constraint-based algorithms |
| Logistics | Optimisation algorithms |
| Selling commitments, agreements, settlements | Human approval |

## Net realisation, not headline price

Illustrative figures only:

| Selling option | Quoted ₹/kg | Costs ₹/kg | Net ₹/kg | Net for 1,000 kg |
|---|---:|---:|---:|---:|
| Local mandi | 20 | 1 | 19 | ₹19,000 |
| Regional mandi | 24 | 3 | 21 | ₹21,000 |
| Distant wholesale market | 27 | 6 | 21 | ₹21,000 |

The highest quoted price is not the highest earning. KisanSetu ranks options by expected net and shows the assumptions behind each.

## Illustrative workflow

A farmer in Gujarat expects 3,000 kg of tomatoes in five days.

1. **Harvest registration** by voice (Crop and Harvest agent)
2. **Market investigation** on net realisation (Market Intelligence agent)
3. **Buyer discovery**: a processor needs 5,000 kg in the window (Buyer Matching agent)
4. **Collective supply**: nearby farmers or an FPO for the other 2,000 kg (Collective Selling agent)
5. **Logistics planning**: vehicle capacity, pickups, delivery cost (Logistics agent)
6. **Transaction proposal**: price, deductions, transport, expected proceeds (orchestrator)
7. **Human approval**: each farmer approves their own commitment
8. **Execution and reconciliation**: dispatch, delivered quantity, payment status (Transaction and Trust agent)

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

## Responsible use

- Recommendations are explained, with price uncertainty shown.
- No guaranteed price-increase claims.
- Farmers can reject any recommendation.
- Consent is required before sharing farmer data with buyers.
- Approval is required before any sale is committed.
- Transactions keep an auditable record.

## How we would measure impact

Target metrics for future evaluation, not results: change in net realisation per kg, farmers accessing new buyers, volume sold collectively, transport cost per kg, share of transactions completed, payment reconciliation time, farmer repeat usage.

## Roadmap

1. One crop, one defined region
2. Validate the workflow with farmers and an FPO
3. Onboard local buyers and transporters
4. Add crops and neighbouring markets
5. Extend through FPOs and institutional partnerships
6. Regional market-access networks

## Repository contents

| Path | Contents |
|---|---|
| `docs/KisanSetu_Pitch_Deck.pdf` | Pitch deck |
| `docs/KisanSetu_Speaker_Script_and_Sources.md` | Speaker script and sources |

<!-- Add prototype code folders here as they land, and say for each data source whether it is live or simulated. -->
