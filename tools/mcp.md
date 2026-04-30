# MCP servers used by hyper-experiments

This file documents the MCP servers this skill registers when it is
installed through `skill-manager`. Agents operating under this skill
talk to all of them through a single endpoint — the **virtual MCP
gateway** — never directly.

## The virtual MCP gateway (what agents see)

When `skill-manager install hyper-experiments` runs, it doesn't add
each MCP server to your agent's MCP config independently. Instead it:

1. Starts (or reuses) the **virtual MCP gateway** (a small FastAPI/MCP
   process living under `~/.skill-manager/`).
2. Registers every MCP dependency declared by every installed skill
   with the gateway.
3. Writes a single `virtual-mcp-gateway` entry into the agent's MCP
   config (`~/.claude.json`, `~/.codex/config.toml`, …) pointing at
   the gateway's HTTP endpoint.

Agents see **one** MCP server. The gateway exposes a fixed, virtual
tool surface for discovering and invoking the real downstream tools:

| Virtual tool          | Use it to …                                                                 |
|-----------------------|-----------------------------------------------------------------------------|
| `browse_mcp_servers`  | List every registered MCP server, deployed or not.                          |
| `describe_mcp_server` | Look up `init_schema`, `default_scope`, `load_type` for one server.         |
| `deploy_mcp_server`   | Spawn an idle server (when `default_scope=session` or auto-deploy skipped). |
| `browse_active_tools` | List the tools currently active downstream (filterable by `server_id`).     |
| `search_tools`        | Lexical search across active tools when you don't know the exact name.      |
| `describe_tool`       | Disclose a tool's schema. Required before `invoke_tool` (gateway gates).    |
| `invoke_tool`         | Call a downstream tool by `tool_path` (`<server_id>/<tool_name>`).          |

The gateway only proxies — it never modifies arguments or results.
Authentication, rate-limiting, and side effects all happen at the
downstream MCP server level.

`tool_path` is always `<server_id>/<tool_name>`. For runpod that
means `runpod/list-endpoints`, `runpod/get-pod`, etc.

### Calling a runpod tool from an agent

```text
1. browse_active_tools(server_id="runpod") → confirm runpod is up
2. describe_tool(tool_path="runpod/list-endpoints") → get schema, satisfies disclosure gate
3. invoke_tool(tool_path="runpod/list-endpoints", arguments={}) → call it
```

Step 2 is mandatory. The gateway refuses `invoke_tool` for tools that
haven't been disclosed in the current session. Calling
`describe_tool` once per session covers every subsequent invoke of
the same tool.

## Registered downstream servers

### runpod (`@runpod/mcp-server`)

- **Load type**: `npm` (skill-manager spawns `npx -y @runpod/mcp-server@latest`)
- **Scope**: `global-sticky` — registered once, persists across
  gateway restarts.
- **Required init**: `RUNPOD_API_KEY` (from
  https://www.runpod.io/console/user/settings).
- **How the API key reaches the subprocess**: see SKILL.md →
  "Installation & runtime dependencies" → "Runpod MCP server". Short
  version: export `RUNPOD_API_KEY` in the shell that runs
  `skill-manager install`. skill-manager folds it into
  `initialization_params`, the gateway's
  `_materialize_client_config` injects it into `ClientConfig.env`,
  and the npx subprocess inherits it.

#### Tools exposed by runpod

The runpod MCP server is a thin wrapper over the RunPod REST API.
Invoke through the virtual gateway as `runpod/<name>`:

| Group               | Read-only                                                              | Mutating                                                            |
|---------------------|------------------------------------------------------------------------|---------------------------------------------------------------------|
| Pods                | `list-pods`, `get-pod`                                                 | `create-pod`, `update-pod`, `start-pod`, `stop-pod`, `delete-pod`   |
| Serverless endpoints| `list-endpoints`, `get-endpoint`                                       | `create-endpoint`, `update-endpoint`, `delete-endpoint`             |
| Templates           | `list-templates`, `get-template`                                       | `create-template`, `update-template`, `delete-template`             |
| Network volumes     | `list-network-volumes`, `get-network-volume`                           | `create-network-volume`, `update-network-volume`, `delete-network-volume` |
| Container registry  | `list-container-registry-auths`, `get-container-registry-auth`         | `create-container-registry-auth`, `delete-container-registry-auth`  |

Mutating tools execute against the real RunPod account associated
with the API key. Use `--dry-run` style narration before calling any
`create-*` / `delete-*` / `start-pod` / `stop-pod` tool, and never
chain mutations without explicit operator approval.

### When to register additional MCP servers

If you find yourself reaching for an MCP server that isn't in this
list, the right move is **not** to invoke `npx`/`docker` directly
from the agent. Instead:

1. Author a skill (or extend this one) that declares the server in
   `skill-manager.toml` under `[[mcp_dependencies]]`. See the
   skill-publisher reference at
   `libs/skill-manager/skill-publisher-skill/SKILL.md`.
2. `skill-manager install <skill>` — the gateway picks the new
   server up automatically.
3. Discover its tools via `browse_active_tools(server_id="<name>")`.

Registering through skill-manager guarantees the gateway gets a
clean spec, the right runtime ({npx, uv, docker, …}) is bundled if
needed, and `init_schema`-declared secrets follow the env-init path
without ever being committed to disk.

## Local install verification

After `RUNPOD_API_KEY=<key> skill-manager install hyper-experiments`
returns, verify end-to-end through the gateway's virtual tools — the
same path agents use. Don't hit the gateway's HTTP surface directly;
the virtual tools are the contract.

From an MCP-capable client (Claude Code, Codex, …):

```text
browse_mcp_servers()                              # runpod should be listed, deployed=true
describe_mcp_server(server_id="runpod")           # confirm load_type=npm, default_scope=global-sticky
browse_active_tools(server_id="runpod")           # list runpod/* tools
describe_tool(tool_path="runpod/list-endpoints")  # disclosure gate
invoke_tool(tool_path="runpod/list-endpoints", arguments={})
```

The reference test that drives this end-to-end is the
`hyper-experiments` graph in
`libs/skill-manager/test_graph/build.gradle.kts`. Its envelope
artifacts under `build/validation-reports/<runId>/` show the full
describe + invoke output for `runpod/list-endpoints` after a fresh
install.
