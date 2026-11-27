- Live app: **https://hack.dobsinsky.dev** (the `/test` page is `https://hack.dobsinsky.dev/test`)
- Code: `git@github.com:michalomegalul/hackathon-27-12-2026.git`
- Server login: `ssh <your-username>@ssh.dobsinsky.dev`

## 1. udelej ssh pokud nemas
```
ssh-keygen -t ed25519
```

```
cat ~/.ssh/id_ed25519.pub
```

posli mi to na discord

## 2. Connect to ssh

```
sudo pacman -S cloudflared
```

Then add this to `~/.ssh/config` (create the file if missing):

```
Host ssh.dobsinsky.dev
  ProxyCommand cloudflared access ssh --hostname %h
  User <USERNAME>
```

Connect:

```
ssh <USERNAME>@ssh.dobsinsky.dev
```

## 3. Working on the project

You are on a shared Linux box. You can use `sudo` and `docker` without a password.

**The app deploys itself.** Every 30 seconds the server checks `main` on GitHub.
If there is a new commit it rebuilds with `docker compose up -d --build`.
30 sec is delay for deploy


Useful commands on the server:

```
cd /opt/app                          # the deployed code
docker compose ps                    # what is running
docker compose logs -f               # live logs
sudo journalctl -u deploy -n 20      # did the last auto-deploy work?
```

## 4. Story2Data app

`docker compose up -d --build` runs two services:

- `app`: Streamlit on port 8501 (Python 3.12, uv). Built from `app/Dockerfile`.
- `web`: nginx on host port 3000. It proxies everything to `app`, with websocket
  headers and a 1 hour read timeout. `/test` is still the static page from `site/`.

`./data` on the host is mounted at `/data` in the container. It holds the LLM cache,
the text pools, the job files and the simulated runs. Back it up before the demo:
the cached demo stories live there.

Run it locally without Docker:

```
uv sync
uv run streamlit run app/main.py
```

### Environment variables

Set them in `.env` next to `compose.yaml` (never commit it). All have defaults.

| Variable | Default | What it does |
|---|---|---|
| `LLM_BACKEND` | `ollama` | `ollama`, `claude` or `replay`. `replay` only serves cached answers and never uses the network. |
| `OLLAMA_URL` | `http://192.168.4.19:11434` | Homelab Ollama (RX 6800, CT 100). |
| `OLLAMA_MODEL` | `gemma4:26b` | Model for every step. `gemma4:12b` is faster. Only one fits in VRAM, a switch costs ~10 s. |
| `OLLAMA_DESKTOP_URL` | empty | Optional second Ollama for text pools only. Health-checked every 60 s, skipped when down. |
| `OLLAMA_DESKTOP_MODEL` | `gemma4:12b` | Model on the desktop worker. |
| `ANTHROPIC_API_KEY` | empty | Enables the `claude` backend and the compiler's fallback after 2 failed retries. |
| `ANTHROPIC_MODEL` | `claude-sonnet-5` | Claude model. |
| `REPLAY_MODEL` | `OLLAMA_MODEL` | In replay mode, prefer answers cached by this model. Any cached model is used if it has none. |
| `DATA_DIR` | `data` (`/data` in Docker) | Job files (`jobs/`) and simulated runs (`runs/`). |
| `LLM_CACHE_DIR` | `data/llm_cache` | Every LLM response, keyed by hash(step, prompt, schema, model). |
| `TEXT_POOL_DIR` | `data/text_pools` | Generated review and ticket pools. |

Every Ollama call sends `num_ctx 16384`, `keep_alive -1` and `stream false`. Calls with a
schema send `think false` plus `format`. A different `num_ctx` would make Ollama reload
the model.

### HTTP API

`docs/API.md` is the contract (every request and response). On the server the `api` service
runs it on port 8000 and nginx sends `/v1/`, `/docs` and `/openapi.json` there. Locally:

```
uv run python -m s2d.api token michal admin          # prints a token, stored in data/api/tokens.json
uv run uvicorn s2d.api.main:app --port 8000          # one process: it holds the job queue
curl -s localhost:8000/v1/health
```

### Before the demo

`scripts/demo_check.sh` runs one small job end to end and prints PASS / FAIL / SKIP per
check (exit 1 on any FAIL): health and the LLM, a job on `examples/a.yaml` with 2000
customers (result, tables, query, ZIP), the student 403 on `/answer-key`, the Streamlit app,
and, with `S2D_TEST_PG`, the Postgres export. About 30 s locally; it needs `curl`, `jq`, `unzip`.

```
S2D_TOKEN=<teacher|admin> S2D_STUDENT_TOKEN=<student> \
  BASE_URL=https://hack.dobsinsky.dev scripts/demo_check.sh     # APP_URL defaults to BASE_URL
S2D_TOKEN=$(uv run python -m s2d.api token check admin) scripts/demo_check.sh   # local, 8000 + 8501
```

Every run leaves one job in the job list ("Pražírna Zrnko", the company of `examples/a.yaml`).

### Command line

```
uv run python -m s2d.compiler examples/stories/pekarna.yaml --out spec.yaml   # story -> spec
uv run python -m s2d.texts generate examples/a.yaml                           # text pools, ~2.5 h on 26b
uv run python -m s2d.texts generate --generic                                 # generic pool
uv run python -m s2d.texts stats data/text_pools/prazirna_zrnko.json
uv run pytest                                  # all tests; integration ones skip if Ollama is down
uv run pytest -m "not integration"             # offline only
uv run pytest -m integration -s                # only the real-Ollama tests, with timings
```
