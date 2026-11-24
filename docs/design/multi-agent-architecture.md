# Multi-agent architecture

**Status:** design, 2026-11-24. This is the heart of KisanSetu. Any change that makes the agents less autonomous must be raised with the team first (see `CLAUDE.md`, Core objectives).

## What "multi-agent" means here

KisanSetu is **not** one model calling seven functions. It is eight agents:

- one **Orchestrator** that owns the farmer's goal and the plan, and
- seven **specialist agents**, each a separate Claude agent with its own instructions, its own tools, its own reasoning loop, its own memory and its own structured output.

The Orchestrator delegates **goals**, not function calls ("find buyers for 3,000 kg of grade-A tomatoes deliverable by Friday within 150 km"). The specialist decides how to achieve the goal, which of its tools to use and in what order, and reports back a result with its confidence, its assumptions and where its data came from. Specialists can **escalate**: report that a goal can't be met as stated and say what would unblock it. The Orchestrator then re-plans and may bring in another agent.

What stays outside the agents, by design:

- **Numbers come from code.** Prices, costs, net realisation, matching scores and routes are computed by deterministic tools. Agents decide what to compute and interpret the results; they never invent a figure.
- **Commitments go through the workflow.** A sale, a collective-participation decision, a transport booking or a settlement is a state in the workflow that only a human approval can advance. No agent has a tool that commits on a farmer's behalf.

## The agents

| Agent | Goal it owns | Tools (deterministic code it can call) | Model (configurable) |
|---|---|---|---|
| **Orchestrator** | Get this farmer (or group) the best informed sale they approve | `delegate`, `await_results`, `read_workflow`, `update_plan`, `request_approval`, `notify_farmer`, `escalate_to_coordinator` | Claude Opus 5.5 |
| **Crop and Harvest Intelligence** | Know what will be ready, where, when, how much and what quality; spot surpluses early | `parse_harvest_report`, `get_farmer_profile`, `record_harvest`, `area_supply_forecast`, `detect_surplus` | Claude Haiku 5.5 |
| **Market Intelligence** | Rank selling options by expected net realisation, with ranges and data provenance | `get_prices` (plug-and-play sources), `get_arrivals`, `price_trend`, `transport_cost`, `net_realisation`, `stale_data_check` | Claude Sonnet 5.5 |
| **Buyer Matching** | Find buyer demand that fits the lot and window, and compare offers | `search_buyer_requirements`, `match_score`, `buyer_history`, `draft_offer_request` (consent-checked) | Claude Sonnet 5.5 |
| **Collective Selling** | Fill gaps and build bigger lots fairly from nearby compatible farmers | `find_compatible_lots` (PostGIS), `aggregate_lots` (OR-Tools CP-SAT), `pro_rata_split`, `compare_individual_vs_collective` | Claude Opus 5.5 |
| **Logistics** | Get the produce there at the lowest sensible cost per kg | `available_vehicles`, `route_pickups` (OR-Tools routing on OSRM), `shared_load_options`, `transport_quote` | Claude Sonnet 5.5 |
| **Storage Decision** | Decide sell-now vs store-and-sell-later with honest uncertainty | `storage_options`, `spoilage_model`, `price_scenarios`, `hold_vs_sell` | Claude Opus 5.5 |
| **Transaction and Trust** | Make every agreed term, delivery and payment traceable | `create_agreement_draft`, `record_dispatch`, `record_delivery`, `reconcile_quantities`, `payment_status`, `issue_receipt` | Claude Sonnet 5.5 |

Models are set per agent in config (`agents/<name>.yaml`), so we can move an agent up or down a tier based on measured quality and cost. Requests to Opus 5.5 and Sonnet 5.5 enable the API's server-side refusal fallbacks.

## How they work together

```
Farmer / FPO coordinator
        │ voice, app, SMS
        ▼
  ┌─────────────┐   goals (delegate)    ┌────────────────────────────┐
  │ Orchestrator │ ───────────────────▶ │ 7 specialist agents         │
  │  plan, state │ ◀─────────────────── │ each: own prompt, tools,    │
  └─────┬───────┘  results, escalations │ loop, memory, output schema │
        │                               └──────────────┬─────────────┘
        │ request_approval                             │ tool calls
        ▼                                              ▼
  Approval gate (workflow state)          Deterministic tools: prices, net
  farmer approves / rejects               realisation, matching, OR-Tools,
                                          routing, ledgers
        ▲                                              │
        └────────── shared workflow state + message log (Postgres) ◀┘
```

1. **Shared state (blackboard).** Each selling workflow has one record in Postgres: the harvest, the current plan, every task and its status, every result, every approval. All agents read it; each agent may write only its own section.
2. **Messages.** Agents talk through an `agent_message` log: `task` (Orchestrator to specialist), `result`, `escalation`, `question` (specialist to Orchestrator), `event` (from the outside world). Every message has a workflow ID, a correlation ID and a timestamp. This log is the audit trail and the demo's "agent trace" view.
3. **Delegation.** The Orchestrator's `delegate(agent, goal, constraints, deadline, acceptance_criteria)` creates a task and queues it. Independent tasks run **in parallel** (for example Market Intelligence and Buyer Matching start together); `await_results` collects them.
4. **Evaluation.** The Orchestrator checks each result against the acceptance criteria it set. If a result is weak (low confidence, stale data, missing quantity), it can re-delegate with tighter constraints or ask another agent.
5. **Escalation and replanning.** A specialist that can't meet its goal returns an escalation with a reason and options ("order needs 5,000 kg, lot is 3,000 kg; could fill from nearby farmers"). External events (buyer withdraws, vehicle cancelled, farmer reports a smaller harvest, new prices) wake the Orchestrator, which re-plans from the current state. Anything already approved is changed only with fresh approval.
6. **Human approval.** `request_approval` moves the workflow into a waiting state and sends the proposal to each affected farmer (app, SMS or voice call, or via their FPO coordinator). The workflow resumes on their answer, which can take days; nothing is held in a model's context while waiting.
7. **Fallback to people.** If an agent fails repeatedly, a budget is exhausted, or confidence stays low, the Orchestrator escalates to the FPO coordinator instead of guessing.

## Agent runtime

- Each agent run is a background job (ARQ worker) that runs that agent's tool-use loop with the Claude API: the agent's system prompt, its tools with strict JSON schemas, the task, and the slice of workflow state it needs.
- Outputs use **structured outputs** with a per-agent schema that always includes `confidence`, `assumptions` and `sources` (source name, data kind, date).
- **Memory:** short-term is the workflow state; long-term is an `agent_memory` table per agent, scoped to farmer, FPO, buyer or market (for example "this buyer downgraded 30% of the last two lots").
- **Budgets:** each run has a turn limit and a token budget; the Orchestrator has a per-workflow budget.
- **Permissions:** tools check the caller agent, the workflow and the farmer's consent (Buyer Matching can't share a farmer's location or name with a buyer without consent on record).
- **Observability:** every model call, tool call and message is traced (OpenTelemetry) and shown in the dashboard's agent-trace timeline.

## The tomato scenario, agent by agent

1. Farmer reports 3,000 kg of tomatoes in five days. Orchestrator sets the goal and delegates intake to **Crop and Harvest**, which structures the report and flags that three nearby farmers expect tomatoes the same week (surplus risk).
2. Orchestrator delegates **Market Intelligence** and **Buyer Matching** in parallel.
3. Market Intelligence ranks local, regional and distant mandis by net realisation (ranges, dated sources). Buyer Matching finds a processor needing 5,000 kg and **escalates**: lot too small.
4. Orchestrator delegates **Collective Selling** to find 2,000 kg from compatible nearby lots; it returns a pooled lot and each farmer's pro-rata share versus selling alone.
5. Orchestrator delegates **Logistics** for one vehicle across the pickups; it returns a route and cost per kg.
6. Orchestrator compares the processor deal against the best mandi option, builds one proposal per farmer, and calls `request_approval`.
7. Each farmer approves their own share. **Transaction and Trust** drafts the agreement and tracks dispatch, delivery and payment.
8. Day 3: the processor withdraws. The event wakes the Orchestrator, which asks Buyer Matching for alternatives and Market Intelligence for refreshed prices, then sends revised proposals for fresh approval.

## Why not a single agent with tools

A single agent with seven tool groups is cheaper, but it can't specialise its instructions or memory per domain, can't run sub-goals in parallel, gives no per-agent accountability in the trace, and is exactly the "chatbot with labels" the pitch promises we are not. We accept the extra cost and control it with per-agent model tiers and budgets.
