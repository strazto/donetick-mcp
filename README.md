# Donetick MCP

Donetick MCP is a Model Context Protocol (MCP) server that lets an assistant manage household chores as a specific [Donetick](https://github.com/donetick/donetick) user. Ask “Which chores are assigned to me?” or “I took the bins out. Mark that done.” Tested with Donetick v0.1.83.

For setup, jump to [a local desktop or CLI client](#connect-a-local-mcp-client) or [hosted ChatGPT](#connect-chatgpt-through-an-openai-tunnel).

## Why choose this server?

I built this for my two-person household. Both of us sign in through SSO, and Donetick password login is disabled. I wanted to decide which account an assistant could use when I granted access to a connection. If the bins are assigned to Sam but Alex takes them out, Alex can use **Donetick — Alex** to mark the chore done. Donetick credits Alex in the task history.

Choose this server when each connection should verify the Donetick account it acts as and credit every completion to that user, even if the account is a circle admin. If one person regularly logs chores for the whole household, a tool that lets them specify who did the work may suit that workflow better.

| Alternative | How it handles accounts and completions |
| --- | --- |
| jason1365/donetick-mcp-server | Signs in with a Donetick username and password. The caller can supply a member ID with `completed_by` when completing a chore. [Setup and tools](https://github.com/jason1365/donetick-mcp-server/blob/fd33f2f35cf7f54367e528eb6ecb71eeb25f1731/README.md) |
| jaredglaser/donetick-mcp | Uses a personal token and also lets the caller record a completion on another member's behalf. [Setup and tools](https://github.com/jaredglaser/donetick-mcp/blob/490bc8cd33ebf0e49de97a0262aa5b8a686c346b/README.md) |
| Donetick's built-in MCP server | On versions that include the `/mcp` endpoint, a client can connect directly over HTTP with an API token. Circle admins and managers can credit another member. [Upstream setup](https://github.com/donetick/donetick/blob/78c43983b9a549e79c19fd88221cb13d6bc95c81/README.md#mcp-server) · [Completion tool](https://github.com/donetick/donetick/blob/78c43983b9a549e79c19fd88221cb13d6bc95c81/internal/mcp/tools_chores.go#L72-L80) |

## Whose account does the assistant use?

**Anyone with access to Donetick — Alex can use its tools as Alex.** Your MCP client or workspace controls who can use that connection. Donetick applies Alex's permissions to the tasks its tools read or change. To limit Sam to acting as Sam, grant Sam access only to **Donetick — Sam**. If a shared chat login has access to both connections, anyone using that login can choose either one.

Run one server process per person, with their personal token and their exact Donetick username in `DONETICK_EXPECTED_USERNAME`. Before acting on a tool call, the server asks Donetick who owns the token. If Sam's token is mounted in Alex's process, the call stops before it reads or changes any tasks. The `whoami` tool reports the verified username and circle ID.

## Work with tasks

Start by finding the task and confirming the account. The tools return the acting user's details alongside the result so you can check who performed a change.

| What you want to do | Tools |
| --- | --- |
| Check the connection's account, look up household member IDs, or find existing labels | `whoami`, `list_members`, `list_labels` |
| Find a chore by name or assignee, read its details, or see who completed it | `list_tasks`, `get_task`, `task_history` |
| Create a chore, edit its schedule, choose assignees, or change its labels | `create_task`, `edit_task`, `assign_task`, `set_task_labels` |
| Mark an occurrence done, skip it, or undo this account's latest completion or skip for that task within five minutes | `complete_task`, `skip_task`, `undo_task` |

To change a task, read it with `get_task` and pass its `updatedAt` as `expected_updated_at` when editing, assigning, or replacing labels. If the server sees a newer version when it checks the task, it asks you to read it again. Include UTC offsets in timestamps. If a write times out, check the task and its history before retrying because Donetick may already have applied it.

## Connect a local MCP client

Use this route when your desktop or CLI client can launch a process that can reach Donetick. The client exchanges tool calls with that process over standard input and output (stdio). Choose uv to run it with Python on the host, or Docker to run it in a container.

For either option, clone this repository. Sign in to Donetick as the person the connection should act as, create a token under **Settings → API Tokens**, and save it in a file readable only by your host user.

### Run with uv

From the checkout, run `uv sync --locked` with [uv](https://docs.astral.sh/uv/). For clients that use `mcpServers`, add an entry like this. Replace the paths, URL and username with your own. Absolute paths let the client launch the server from any directory.

```json
{
  "mcpServers": {
    "donetick-alex": {
      "command": "uv",
      "args": ["run", "--project", "/absolute/path/to/donetick-mcp", "--locked", "donetick-mcp"],
      "env": {
        "DONETICK_BASE_URL": "https://tasks.example.com",
        "DONETICK_EXPECTED_USERNAME": "alex",
        "DONETICK_TOKEN_FILE": "/absolute/path/to/alex.token",
        "DONETICK_CONNECTION_NAME": "Donetick — Alex",
        "DONETICK_TIMEZONE": "Europe/Paris"
      }
    }
  }
}
```

### Run the local server in Docker

Build the stdio image once from the checkout with `docker build -t donetick-mcp .`. Configure your client to launch a container for each session. The `-i` flag keeps stdin open for tool calls.

In this Linux example, replace `1000:1000` with the UID and GID of the token file's owner (run `id -u` and `id -g` as that user). This lets the process read the private file mounted inside the container. Replace the host path, Donetick URL, and username with your own.

```json
{
  "mcpServers": {
    "donetick-alex": {
      "command": "docker",
      "args": [
        "run", "--rm", "-i", "--user", "1000:1000",
        "--mount", "type=bind,src=/absolute/path/to/alex.token,dst=/run/secrets/donetick-token,readonly",
        "-e", "DONETICK_TOKEN_FILE=/run/secrets/donetick-token",
        "-e", "DONETICK_BASE_URL=https://tasks.example.com",
        "-e", "DONETICK_EXPECTED_USERNAME=alex",
        "-e", "DONETICK_CONNECTION_NAME=Donetick — Alex",
        "donetick-mcp"
      ]
    }
  }
}
```

### Verify the local connection

After saving either configuration, ask your client to call `whoami` on `donetick-alex`. Check that `actor.username` is `alex` (or the username you configured) before asking it to change a chore.

## Connect ChatGPT through an OpenAI tunnel

Use a tunnel when ChatGPT needs to call a server inside your home network. A tunnel client on your host polls OpenAI over outbound HTTPS, passes each request to `donetick-mcp` over stdio, and sends the result back to ChatGPT. Only the container needs to reach your Donetick instance. You can keep the MCP server private without publishing a port or configuring a reverse proxy.

The **tunnel ID** tells OpenAI which connection to route calls through. The **OpenAI runtime API key** authorizes the tunnel client to use that tunnel. The **Donetick personal token** authorizes the resulting task operations as one person. For two people, run two services with distinct tunnel IDs, connection names, expected usernames, and personal tokens. They can share an OpenAI runtime key if it has access to both tunnels.

### Docker Compose example

This service keeps Alex's tunnel available even when Alex's computer is off. Clone this repository on an always-on host that can reach OpenAI and Donetick, then follow the steps from that checkout.

1. Create a tunnel in OpenAI Platform, associate it with your ChatGPT workspace, and copy its ID. Create a restricted OpenAI API key with **Tunnels Read + Use**. The account that owns the key also needs those permissions. [OpenAI's secure MCP tunnel guide](https://developers.openai.com/api/docs/guides/secure-mcp-tunnels)
2. In Donetick, sign in as Alex and create a personal token under **Settings → API Tokens**. In the repository checkout, create a `secrets/` directory. Save the Donetick token in `secrets/alex.token` and the OpenAI runtime key in `secrets/openai-runtime.key`, one value per file. Both files should be owned by the user running Compose and readable only by that user.
3. Save the following as `compose.yaml` beside the Dockerfile. Set the URL to one the container can reach and replace `alex` with the actual Donetick username.

```yaml
services:
  donetick-alex:
    build:
      context: .
      target: tunnel
    restart: unless-stopped
    # Use the file owner's Linux IDs so the container can read the two private files.
    user: "${HOST_UID:?set HOST_UID}:${HOST_GID:?set HOST_GID}"
    environment:
      DONETICK_BASE_URL: https://tasks.example.com
      DONETICK_EXPECTED_USERNAME: alex
      DONETICK_CONNECTION_NAME: Donetick — Alex
      DONETICK_TOKEN_FILE: /run/secrets/donetick-token
      CONTROL_PLANE_TUNNEL_ID: "${ALEX_TUNNEL_ID:?set ALEX_TUNNEL_ID}"
      CONTROL_PLANE_API_KEY: file:/run/secrets/openai-key
    secrets:
      - donetick-token
      - openai-key

secrets:
  donetick-token:
    file: ./secrets/alex.token
  openai-key:
    file: ./secrets/openai-runtime.key
```

Set the tunnel ID and start the service from the checkout. Leave it running while ChatGPT discovers and calls the tools.

```sh
export HOST_UID="$(id -u)" HOST_GID="$(id -g)"
export ALEX_TUNNEL_ID="tunnel_replace_with_your_id"
docker compose up -d --build donetick-alex
```

In ChatGPT, add a custom MCP connection named **Donetick — Alex**, choose **Tunnel**, and select Alex's tunnel. Choose **No authentication** for the MCP server because the container already supplies Alex's Donetick token. Ask that connection to call `whoami`. A reply with `actor.username` equal to `alex` verifies both the tunnel and the Donetick credential end to end.

## Connection settings

Use the same settings whether uv, Docker, or the tunnel client starts the server.

| Variable | What to supply |
| --- | --- |
| `DONETICK_BASE_URL` | Instance URL as reachable from the server process, for example `https://tasks.example.com`. The server adds `/api/v1` to requests. |
| `DONETICK_EXPECTED_USERNAME` | Exact Donetick username that must match the token owner's profile. |
| `DONETICK_TOKEN_FILE` or `DONETICK_TOKEN` | Set exactly one. Supply the path to a file containing the personal token, or pass the token value through the process environment. |
| `DONETICK_CONNECTION_NAME` | Name the server reports to the MCP client. Defaults to `Donetick`. |
| `DONETICK_TIMEZONE` | IANA time zone for new tasks, such as `Europe/Paris`. Defaults to `UTC`. A task can override it with `frequencyMetadata.timezone`. |

## Development

Run the fixture tests to check the tools and the stdio connection without a Donetick account. Build the package to check that it can be distributed.

```sh
uv run --locked python -m unittest discover -s tests -v
uv build
```

To test against a real Donetick version, configure a disposable account with the connection settings above and run `uv run --locked python scripts/live_test.py --apply`. The script creates a temporary task and label, checks edits and completion credit, and removes the test data.
