# KisanSetu — working rules

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
