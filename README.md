# Donetick MCP

An MCP server for managing [Donetick](https://github.com/donetick/donetick) tasks with a personal API token. Each server process acts as one Donetick user and checks the token's owner before every tool call. Tested with Donetick v0.1.83.

## Run with uv

Clone this repository and install the locked dependencies with [uv](https://docs.astral.sh/uv/).

~~~sh
uv sync --locked
~~~

Create a personal API token in Donetick under **Settings → API Tokens** and save it to a file readable by your user. Configure your MCP client to launch the server over stdio. For example, in a client that uses `mcpServers`:

~~~json
{
  "mcpServers": {
    "donetick": {
      "command": "uv",
      "args": ["run", "--project", "/absolute/path/to/donetick-mcp", "--locked", "donetick-mcp"],
      "env": {
        "DONETICK_BASE_URL": "https://tasks.example.com",
        "DONETICK_EXPECTED_USERNAME": "alex",
        "DONETICK_TOKEN_FILE": "/absolute/path/to/donetick.token",
        "DONETICK_TIMEZONE": "Europe/Paris"
      }
    }
  }
}
~~~

Call `whoami` to check the account and default time zone. For multiple people, configure one named connection and token per person.

| Variable | Meaning |
| --- | --- |
| `DONETICK_BASE_URL` | Required. Instance URL, including the scheme, without the `/api/v1` suffix. |
| `DONETICK_EXPECTED_USERNAME` | Required. Exact Donetick username that owns the token. |
| `DONETICK_TOKEN_FILE` or `DONETICK_TOKEN` | Supply one. A file containing the personal token, or the token value provided by the process environment. |
| `DONETICK_TIMEZONE` | Default IANA time zone for new tasks. Defaults to `UTC`. A task can specify its own zone in `frequencyMetadata.timezone`. |
| `DONETICK_CONNECTION_NAME` | Display name reported to MCP clients. Defaults to `Donetick`. |

## Tools

| Use | Tools |
| --- | --- |
| Identify the account and find people and labels | `whoami`, `list_members`, `list_labels` |
| Find tasks and check their history | `list_tasks`, `get_task`, `task_history` |
| Create or change a task | `create_task`, `edit_task`, `assign_task`, `set_task_labels` |
| Record or undo an occurrence | `complete_task`, `skip_task`, `undo_task` |

Pass the `updatedAt` from a recent `get_task` result when editing, assigning, or changing labels. Provide timestamps with UTC offsets. If a write times out, check the task and history before retrying. Task completions are credited to the connection's account.

## Docker

The default image runs the same stdio command. With the variables above exported and `DONETICK_TOKEN_FILE` set to an absolute path:

~~~sh
docker build -t donetick-mcp .
docker run --rm -i --user "$(id -u):$(id -g)" \
  -e DONETICK_BASE_URL -e DONETICK_EXPECTED_USERNAME -e DONETICK_TIMEZONE \
  -e DONETICK_TOKEN_FILE=/run/secrets/donetick-token \
  --mount "type=bind,src=$DONETICK_TOKEN_FILE,dst=/run/secrets/donetick-token,readonly" \
  donetick-mcp
~~~

For [OpenAI secure MCP tunnels](https://developers.openai.com/api/docs/guides/secure-mcp-tunnels), build with `docker build --target tunnel -t donetick-mcp-tunnel .`. This target runs `tunnel-client run --mcp.command donetick-mcp`. Supply the same Donetick settings plus the tunnel client's `CONTROL_PLANE_TUNNEL_ID` and `CONTROL_PLANE_API_KEY` (for example, `file:/run/secrets/openai-key` for a mounted runtime key).

## Development

~~~sh
uv run --locked python -m unittest discover -s tests -v
uv build
~~~

The tests use fixtures, including a local HTTP server for the stdio round trip. To exercise a real instance, configure a disposable account with the variables above and run `uv run --locked python scripts/live_test.py --apply`. This check creates a temporary task and label, exercises the write tools, and removes its fixtures.
