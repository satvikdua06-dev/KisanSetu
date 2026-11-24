# KisanSetu — working rules

## Core objectives (read first, every task)

KisanSetu is a **multi-agent agentic AI market-access network** for Tech4Bharat 2026, Problem Statement 6.1: *farmers sell at the wrong time, place and price.* Every design, document and line of code must serve these objectives. They are not trade-offs to make quietly.

1. **Problem 6.1 first.** Everything exists to help small and marginal farmers sell at a better time, place and price. Logistics, storage and buyer discovery are supporting parts of that, never separate products.
2. **Genuinely multi-agent.** One Orchestrator plus seven autonomous specialist agents (Crop and Harvest, Market Intelligence, Buyer Matching, Collective Selling, Logistics, Storage Decision, Transaction and Trust). Each specialist is its own Claude agent with its own prompt, tools, loop, memory and output schema. The Orchestrator delegates goals, specialists can escalate, and the system replans. Never collapse the agents into functions or tools of one model. Source: `docs/design/multi-agent-architecture.md`.
3. **Net realisation, computed by code.** Options are ranked by what the farmer actually earns after costs, with ranges and dated sources. Prices, costs, matching and routing come from deterministic code; the LLM never invents a number.
4. **The farmer decides.** Every sale, collective participation, transport booking and settlement needs that farmer's explicit approval, enforced by the workflow, not by an agent's choice. Consent before sharing farmer data.
5. **Honest about data and maturity.** Every price, demand or offer is labelled observed, historical, forecast or simulated, with source and date. Never claim results, users, partners or accuracy we don't have.
6. **Built for real farmers.** Voice-first in their language, works offline and over SMS or voice calls, FPO coordinator can assist. One codebase for Android, iOS and web.
7. **Plug-and-play data.** Price sources are added by configuration, not code (`docs/design/market-price-sources.md`).

Sources of truth, in order: this section, `docs/design/multi-agent-architecture.md`, `docs/STACK.md`, `docs/design/*`, `README.md`, `docs/KisanSetu_Submission_Text.txt`.

### Drift check (mandatory)

Before finishing any task that changes design, docs or code, check the result against each objective above and say in the reply that you did. If a choice would weaken any objective, even to save cost, time or complexity:

- **stop and ask the user first**, stating which objective it touches and what the alternative costs;
- never make that trade silently or bury it in wording (for example describing agents as "tools the orchestrator calls");
- if you find existing drift in the repo, flag it and propose the fix rather than building on top of it.

## Live design board

Live FigJam board: https://www.figma.com/board/ss0wK9DgPvP7g5XYQNYfxG

While working on any task in this repo, keep the board in step with the work:

- At each milestone (a new component, endpoint, agent, schema, data source, or a change to the flow), add or update a diagram on the board with the Figma MCP `generate_diagram` tool, passing `fileKey: ss0wK9DgPvP7g5XYQNYfxG` so it lands on this board instead of a new file.
- Pick the diagram type to fit: `flowchart` for architecture and data flow, `sequenceDiagram` for agent hand-offs, `erDiagram` for database schema, `stateDiagram-v2` for workflow and approval states, `gantt` for plans.
- Prefix every diagram name with `KisanSetu - ` and describe it so the latest one is easy to identify (for example `KisanSetu - DB Schema v2`).
- Label data as observed, historical, forecast or simulated, the same way the README does.
- Batch updates: one diagram per milestone, not per file edit. The Figma plan is Starter, so MCP calls are rate limited.
- Mention in the turn's reply which diagrams were added.

## Notion work log

Hub page: https://app.notion.com/p/422055926820812f94c0f51cf9b5847a (private draft in the user's workspace)

- **Work Log database** — data source `collection://42205592-6820-8130-ba86-000bb514bd91`. Add one row per piece of work with `notion-create-pages` (parent `data_source_id`). Properties: `Task` (title), `Status` (Planned / In progress / Done / Blocked), `Area` (multi-select: Docs, Backend, Frontend, Agents, Data, Design, Infra), `date:Date:start` (YYYY-MM-DD), `Summary`, `Files`, `Commit` (GitHub commit URL), `Figma diagram` (names of diagrams added). Create the row as `In progress` when work starts and update it to `Done` (with commit and diagrams) when it lands.
- **Workstream pages** — a larger piece of work (a new module, agent, or feature spanning several sessions) gets its own child page under the hub page (`parent.page_id` = hub id), holding the plan, decisions, open questions and links back to its Work Log rows.
- **KisanSetu Workstreams folder** — folder id `42205592-6820-8197-b98b-c2398797f907`, owned by the hub page. When a new workstream starts, add a nested folder for it with `notion-create-folder` (`parent.folder_id`) to hold its files and exports.
- Log what actually happened. Don't mark something Done that wasn't verified; say what was skipped.
- Mention the Notion updates in the turn's reply alongside the Figma ones.

## Commits

Commit as the user only. No Claude co-author trailers or "Generated with Claude Code" lines.
