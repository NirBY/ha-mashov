# Homework checklists and MCP

Each child gets a native Home Assistant `todo` entity when homework fetching is enabled.
The list belongs to the child's existing device. Check or uncheck assignments in HA's
To-do panel or a `todo-list` dashboard card. Generated Mashov Live dashboards include
the child's checklist in their pop-up after the dashboard is regenerated.

Completion is stored locally, separately for each account, child, school year and
assignment. It survives refreshes, reloads and restarts. Changing assignment text
creates an open task. Empty homework is ignored and identical duplicate records are
collapsed. Lesson dates appear in descriptions: they are not assumed to be deadlines.
Assignments cannot be renamed, created or deleted through this list. No completion
or edit is sent to Mashov. Lists cover the configured homework date window; completed
markers are retained when a task temporarily leaves that window. Deleting a hub
removes its completion store as well as its portal cache.

## MCP through Home Assistant

The integration registers a separate read-only LLM API for each account **only after
enabling “Expose this account to MCP / Assist”** in that hub's Configure form. The
default is off for both existing and new installations.

Add Home Assistant's built-in **Model Context Protocol Server** integration. In its
options, disable **Expose all LLM APIs**, select only the intended `Mashov – … (read
only)` APIs and retain **Require admin**. Connect your MCP client to the HA server's
`/api/mcp` endpoint using its supported OAuth flow. Never embed passwords or tokens in
dashboard YAML. Client authentication is separate from enabling this server API.

Tools:

- `mashov__catalog`: children and enabled dataset names for that account.
- `mashov__read`: full cached selected dataset, optionally paginated with `offset`
  and `limit` (1–100, default 25). Use the catalog's `student_id` for student data.
  Holidays and mailbox belong to the account rather than an individual child.

All supported data categories are accessible when selected for fetching: homework,
behavior, weekly plans, timetables, lesson history, grades, holidays, optional student
resources and mailbox. Source status and staleness accompany each response. Follow
`next_offset` until null for complete results. A failed source does not imply an empty
successful result. Calls do not refresh the portal, change homework, mark messages
read or control devices. Mailbox bodies require the existing full-content opt-in;
the existing fetching behavior of that option still marks conversations read in Mashov.

The API checks that the caller is an authenticated HA administrator and that the hub
still permits MCP on every call, including calls from a previously created session.
Disabling a source immediately prevents API reads of that source. Credentials,
session cookies and raw authentication caches are never returned. HA's own MCP
transport controls which client can reach these APIs. Visibility on a dashboard is
not an access-control mechanism for school data.

## Other bots and MCP clients

Use the same server URL, `https://YOUR_HA_HOST/api/mcp`, for compatible clients.
Select **Streamable HTTP** (sometimes called HTTP) and **OAuth**, then sign in with
an HA administrator account. Home Assistant supports PKCE and OAuth Client ID
Metadata Documents (CIMD); clients that only support Dynamic Client Registration
(DCR) may not connect. A cloud-hosted client must be able to reach the HA URL over
HTTPS. Client availability and setup screens depend on the client and account.

- **Claude:** Settings → Connectors → Add custom connector. Enter the server URL,
  use Claude's published OAuth identity when offered, and select Connect.
- **Codex:** run `codex mcp add mashov --url https://YOUR_HA_HOST/api/mcp`, then
  `codex mcp login mashov` if authentication is still required.
- **A custom bot:** attach an MCP client to the bot backend, authenticate with HA,
  discover tools using `tools/list`, and invoke the selected tool using `tools/call`.
  Preserve the discovered tool names: HA may namespace them when several APIs are
  selected. Use the catalog first to identify the child, then read the requested
  dataset and follow pagination. Present source status and freshness to the user.
- **Telegram / WhatsApp bots:** connect the messaging bot's backend to MCP through
  such an adapter. Verify the sender before returning school data, restrict access
  to the intended family, and keep authorization tokens in backend secret storage.
  Connecting HA to MCP does not automatically connect a messaging bot or grant its
  users access.

Suggested first request: “List the children, then summarize homework for each child
using the Mashov tools.” Only information already selected for collection is exposed;
the connection does not enable additional datasets or mailbox-body fetching.

Official references: [MCP Server and client examples](https://www.home-assistant.io/integrations/mcp_server/),
[To-do lists](https://www.home-assistant.io/integrations/todo/).
