# Donetick MCP

Ask your assistant “What chores are assigned to me this week?” or “I took the bins out. Mark that done.” This MCP server gives the assistant tools to look up tasks, read their history, and record changes in your [Donetick](https://github.com/donetick/donetick) instance. Tested with Donetick v0.1.83.

## Whose account does the assistant use?

Each connection acts as one Donetick user. Suppose Alex and Sam share a Donetick circle and “Take out the bins” is assigned to Sam. If Alex takes the bins out and marks the task done through **Donetick — Alex**, Donetick credits Alex in the task history. When Sam does the chore next week, Sam uses **Donetick — Sam**.

Set up one server process per person. Give it that person's Donetick personal API token and set `DONETICK_EXPECTED_USERNAME` to the username on their Donetick profile. Before acting on a tool call, the server looks up the token owner's profile. If the username differs, the call fails before it reads or changes any tasks. This catches mistakes such as mounting Sam's token in Alex's container.

The connection name helps people pick an account. Anyone who can use **Donetick — Alex** can act with Alex's permissions, regardless of who is signed in to the chat. Give each person access to the appropriate connection in your MCP client. On a shared chat login, select or name the connection explicitly. Ask it to call `whoami` to see the Donetick username and circle ID it will use.

## Connect a local MCP client with uv

Use this setup when your desktop or CLI client can launch a command on a machine that can reach Donetick. The client starts the server and exchanges tool calls over standard input and output (stdio). For hosted ChatGPT, use the [tunnel setup](#connect-chatgpt-through-an-openai-tunnel) instead.

Clone this repository and run `uv sync --locked` in the checkout with [uv](https://docs.astral.sh/uv/). Sign in to Donetick as the person the connection should act as. Under **Settings → API Tokens**, create a personal token and save it in a file readable only by that user on the host.

For clients that use `mcpServers`, add an entry like this. Replace the paths, URL and username with your own. The client needs the absolute paths because it can start the process from any directory.

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

## Connection settings

Use the same settings whether uv, Docker, or the tunnel client starts the server.

| Variable | What to supply |
| --- | --- |
| `DONETICK_BASE_URL` | Instance URL as reachable from the server process, for example `https://tasks.example.com`. The server adds `/api/v1` to requests. |
| `DONETICK_EXPECTED_USERNAME` | Exact Donetick username that must match the token owner's profile. |
| `DONETICK_TOKEN_FILE` or `DONETICK_TOKEN` | Set exactly one. Supply the path to a file containing the personal token, or pass the token value through the process environment. |
| `DONETICK_CONNECTION_NAME` | Name the server reports to the MCP client. Defaults to `Donetick`. |
| `DONETICK_TIMEZONE` | IANA time zone for new tasks, such as `Europe/Paris`. Defaults to `UTC`. A task can override it with `frequencyMetadata.timezone`. |

## Run the local server in Docker

Use the default image if your client can launch Docker and you want the container to supply Python and the dependencies. Build it once from the checkout. For each session, run the second command from a shell script your client launches with the connection settings in its environment. Set `DONETICK_TOKEN_FILE` to an absolute host path. The `-i` flag keeps stdin open for tool calls. On Linux, `--user` lets the process read a token file owned by your host user.

```sh
docker build -t donetick-mcp .
docker run --rm -i --user "$(id -u):$(id -g)" \
  -e DONETICK_BASE_URL -e DONETICK_EXPECTED_USERNAME \
  -e DONETICK_CONNECTION_NAME -e DONETICK_TIMEZONE \
  -e DONETICK_TOKEN_FILE=/run/secrets/donetick-token \
  --mount "type=bind,src=$DONETICK_TOKEN_FILE,dst=/run/secrets/donetick-token,readonly" \
  donetick-mcp
```

## Connect ChatGPT through an OpenAI tunnel

Use a tunnel when ChatGPT needs to call a server inside your home network. A tunnel client on your host polls OpenAI over outbound HTTPS, passes each request to `donetick-mcp` over stdio, and sends the result back to ChatGPT. Only the container needs to reach your Donetick instance. You can keep the MCP server private without publishing a port or configuring a reverse proxy.

The **tunnel ID** tells OpenAI which connection to route calls through. The **OpenAI runtime API key** authorizes the tunnel client to use that tunnel. The **Donetick personal token** authorizes the resulting task operations as one person. For two people, run two services with distinct tunnel IDs, connection names, expected usernames, and personal tokens. They can share an OpenAI runtime key if it has access to both tunnels.

### Docker Compose example

This service keeps Alex's tunnel available even when Alex's computer is off. Run it on an always-on host that can reach OpenAI and Donetick.

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

## Work with tasks

Start by finding the task and confirming the account. The tools return the acting user's details alongside the result so you can check who performed a change.

| What you want to do | Tools |
| --- | --- |
| Check the connection's account, look up household member IDs, or find existing labels | `whoami`, `list_members`, `list_labels` |
| Find a chore by name or assignee, read its details, or see who completed it | `list_tasks`, `get_task`, `task_history` |
| Create a chore, edit its schedule, choose assignees, or change its labels | `create_task`, `edit_task`, `assign_task`, `set_task_labels` |
| Mark an occurrence done, skip it, or undo the most recent action | `complete_task`, `skip_task`, `undo_task` |

To change a task, read it with `get_task` and pass its `updatedAt` as `expected_updated_at` when editing, assigning, or replacing labels. If the server sees a newer version when it checks the task, it asks you to read it again. Include UTC offsets in timestamps. If a write times out, check the task and its history before retrying because Donetick may already have applied it.

## Development

Run the fixture tests to check the tools and the stdio connection without a Donetick account. Build the package to check that it can be distributed.

```sh
uv run --locked python -m unittest discover -s tests -v
uv build
```

To test against a real Donetick version, configure a disposable account with the connection settings above and run `uv run --locked python scripts/live_test.py --apply`. The script creates a temporary task and label, checks edits and completion credit, and removes the test data.
