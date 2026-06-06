# context-overlay

`context-overlay` is a lightweight OpenAI-compatible request proxy.

It sits between an OpenAI SDK client and an upstream OpenAI-compatible model
server. For each request, it can match configurable conditions, inject extra
context, patch prompts, route to another upstream, or reject the request.

It is intentionally small:

- It does not run an agent loop.
- It does not execute tools.
- It does not interpret model outputs.
- It preserves normal OpenAI-compatible request fields such as `tools`,
  `image_url`, `response_format`, and `stream`.
- Skill injection is just one content source, not a hard-coded runtime mode.

Typical uses:

- Add planning skills before a model sees a task.
- Insert policies, memory, profile text, or prompt overlays.
- Patch a known prompt fingerprint with `regex_replace`.
- Route selected requests to another OpenAI-compatible upstream.
- Expose a local model server through `cloudflared` quick tunnels.

## Install

```bash
pip install context-overlay
```

For local development:

```bash
pip install -e ".[dev]"
pytest -q
```

Check the installed version:

```python
import context_overlay

print(context_overlay.__version__)
```

## Minimal Quick Start

Assume your upstream model server is available at `http://127.0.0.1:8010/v1`.

Create `config.yaml`:

```yaml
upstream:
  base_url: "http://127.0.0.1:8010/v1"
  api_key: "unused"
  timeout_seconds: 600

auth:
  api_key: "proxy-key"

rules:
  - name: add_short_system_overlay
    match:
      path: "/v1/chat/completions"
      messages_regex:
        - "scientific"
    transforms:
      - type: append_system
        content: "When relevant, produce a concrete, evidence-grounded plan before solving."
```

Run the proxy:

```bash
context-overlay serve --config config.yaml --host 127.0.0.1 --port 8011
```

Call it with the OpenAI SDK:

```python
from openai import OpenAI

client = OpenAI(api_key="proxy-key", base_url="http://127.0.0.1:8011/v1")

response = client.chat.completions.create(
    model="Qwen3.5-9B",
    messages=[{"role": "user", "content": "Analyze this scientific task."}],
)

print(response.choices[0].message.content)
```

## Verified End-to-End Echo Overlay Example

This example demonstrates the full path:

```text
OpenAI SDK client -> context-overlay proxy -> local echo upstream -> response
```

The upstream returns the last user message exactly as it receives it. The proxy
changes `test` to `test[skill]` only when the user message contains `test`.

Create `upstream.py`:

```python
from fastapi import FastAPI, Request

app = FastAPI()


@app.get("/v1/models")
async def models():
    return {"object": "list", "data": [{"id": "echo-model", "object": "model"}]}


@app.post("/v1/chat/completions")
async def chat(request: Request):
    body = await request.json()
    messages = body.get("messages") or []
    last_user = ""
    for message in reversed(messages):
        if message.get("role") == "user":
            last_user = str(message.get("content", ""))
            break
    return {
        "id": "chatcmpl-echo",
        "object": "chat.completion",
        "model": body.get("model", "echo-model"),
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": last_user},
                "finish_reason": "stop",
            }
        ],
    }
```

Run the echo upstream:

```bash
uvicorn upstream:app --host 127.0.0.1 --port 19210
```

Create `config.yaml`:

```yaml
upstream:
  base_url: "http://127.0.0.1:19210/v1"
  api_key: "unused"
  timeout_seconds: 30

auth:
  api_key: "proxy-key"

rules:
  - name: insert_skill_after_test
    match:
      path: "/v1/chat/completions"
      messages_regex:
        - "test"
    transforms:
      - type: regex_replace
        target: user
        pattern: "test"
        replacement: "test[skill]"
```

Run the proxy:

```bash
context-overlay serve --config config.yaml --host 127.0.0.1 --port 19211
```

Local checks:

```bash
curl -sS \
  -H "Authorization: Bearer proxy-key" \
  -H "Content-Type: application/json" \
  http://127.0.0.1:19211/v1/chat/completions \
  -d '{"model":"echo-model","messages":[{"role":"user","content":"hello world"}]}'
```

Expected assistant content:

```text
hello world
```

```bash
curl -sS \
  -H "Authorization: Bearer proxy-key" \
  -H "Content-Type: application/json" \
  http://127.0.0.1:19211/v1/chat/completions \
  -d '{"model":"echo-model","messages":[{"role":"user","content":"hello test world"}]}'
```

Expected assistant content:

```text
hello test[skill] world
```

The same behavior is covered by the automated test:

```bash
pytest -q tests/test_end_to_end_echo.py
```

## Configuration Overview

Top-level config:

```yaml
upstream:
  base_url: "http://127.0.0.1:8010/v1"
  api_key: "unused"
  timeout_seconds: 600

auth:
  api_key: "proxy-key"

rules:
  - name: rule_name
    match: {}
    transforms: []
```

### `upstream`

`upstream.base_url` is required. It should include `/v1`.

```yaml
upstream:
  base_url: "http://127.0.0.1:8010/v1"
  api_key: "unused"
  timeout_seconds: 600
```

Fields:

- `base_url`: Upstream OpenAI-compatible base URL.
- `api_key`: Bearer token sent to the upstream. Omit or set to `unused` if the upstream does not require one.
- `timeout_seconds`: HTTP timeout for upstream requests. Default: `600`.

### `auth`

`auth.api_key` protects the proxy itself.

```yaml
auth:
  api_key: "proxy-key"
```

If set, clients must call the proxy with:

```http
Authorization: Bearer proxy-key
```

If omitted, the proxy does not require client authentication. Do not expose an
unauthenticated proxy publicly.

### Environment Variables In Config

String values in YAML are expanded with `os.path.expandvars`.

```yaml
upstream:
  base_url: "${UPSTREAM_BASE_URL}"
  api_key: "${UPSTREAM_API_KEY}"

auth:
  api_key: "${CONTEXT_OVERLAY_API_KEY}"
```

## Rule Matching

Each rule has a `match` block and a list of `transforms`.

```yaml
rules:
  - name: inject_when_user_mentions_rcb
    match:
      path: "/v1/chat/completions"
      model_regex: "Qwen|gpt"
      messages_regex:
        - "scientific"
        - "report"
      extra_body:
        skill_role: "solver"
    transforms:
      - type: append_system
        content: "Use a checklist-aware scientific planning workflow."
```

Supported `match` fields:

- `path`: Exact request path, for example `/v1/chat/completions`.
- `model_regex`: Regular expression matched against `body["model"]`.
- `messages_regex`: List of regular expressions. All must match the concatenated text from chat messages. Matching is case-insensitive.
- `extra_body`: Exact key-value subset that must appear in the request body.

If a rule does not match, it is skipped.

If multiple rules match, they are applied in config order.

## Transform Types

Transforms modify the request body before it is forwarded to the upstream.

`insert_before`, `insert_after`, and `regex_replace` support:

- `target: system`: patch the system message. This is the default.
- `target: user`: patch the last user message.

When `target: user` is used on a multimodal user message, only text blocks are
converted into the patched text message. Use user-message patching only when
that behavior is acceptable for your request.

### `append_system`

Append content to the system message. If no system message exists, one is created at the beginning.

```yaml
transforms:
  - type: append_system
    content: "Prefer concrete evidence over guesses."
```

Before:

```json
{"messages": [{"role": "user", "content": "hello"}]}
```

After:

```json
{
  "messages": [
    {"role": "system", "content": "Prefer concrete evidence over guesses."},
    {"role": "user", "content": "hello"}
  ]
}
```

### `prepend_system`

Prepend content to the system message.

```yaml
transforms:
  - type: prepend_system
    content: "You are operating under this high-priority context."
```

### `append_user`

Append content to the last user message.

```yaml
transforms:
  - type: append_user
    content: "Return the final answer as concise Markdown."
```

If the user message is multimodal, only text blocks are converted into text for
the patched user message. Use user-message transforms only when that behavior is
acceptable. System transforms preserve multimodal request bodies.

### `prepend_user`

Prepend content to the last user message.

```yaml
transforms:
  - type: prepend_user
    content: "Before answering, inspect the task requirements carefully."
```

### `insert_before`

Insert content before the first regex match in the system message.

```yaml
transforms:
  - type: insert_before
    pattern: "Current date:"
    content: "Additional operating guidance."
```

If `pattern` is omitted, this behaves like `prepend_system`.

### `insert_after`

Insert content after the first regex match in the system message.

```yaml
transforms:
  - type: insert_after
    pattern: "# Benchmark Role Overlay"
    content: "Use the following injected planning skills when relevant."
```

If `pattern` is omitted, this behaves like `append_system`.

### `regex_replace`

Replace text in the system message.

```yaml
transforms:
  - type: regex_replace
    target: system
    pattern: "Return a short answer\\."
    replacement: "Return a complete, self-contained answer."
```

Patch the last user message:

```yaml
transforms:
  - type: regex_replace
    target: user
    pattern: "test"
    replacement: "test[skill]"
```

If `replacement` is omitted, the resolved `content` is used as the replacement.

```yaml
transforms:
  - type: regex_replace
    pattern: "OLD_PROMPT_FINGERPRINT"
    content:
      type: file
      path: "./overlays/new_prompt.md"
```

### `route`

Change the upstream base URL and/or model for a matched request.

```yaml
rules:
  - name: route_large_model
    match:
      model_regex: "large"
    transforms:
      - type: route
        upstream_base_url: "http://127.0.0.1:8020/v1"
        model: "Qwen3.5-72B"
```

The routing marker is removed before the request is forwarded.

### `reject`

Reject a matched request with HTTP 403.

```yaml
rules:
  - name: reject_unapproved_mode
    match:
      extra_body:
        unsafe_mode: true
    transforms:
      - type: reject
        reason: "unsafe_mode is not allowed through this proxy"
```

## Content Sources

The `content` field can be a direct string or a structured content source.

### Direct String

```yaml
content: "This text is inserted directly."
```

### Text Source

```yaml
content:
  type: text
  text: "This text is inserted directly."
```

### File Source

```yaml
content:
  type: file
  path: "./overlays/solver_skills.md"
```

The file is read as UTF-8 on each request.

### Skill Directory Source

```yaml
content:
  type: skill_dir
  path: "./skills/generated_skills"
  top_k: 3
  max_chars: 24000
  title: "Relevant Planning Skills"
```

`skill_dir` reads `*.json` files from the directory, retrieves the top-k most
relevant skills using lexical token overlap, and renders them as natural
language.

Expected skill JSON fields:

```json
{
  "name": "glacier_mass_balance_plan",
  "description": "Plan a glacier mass-balance analysis with concrete validation artifacts.",
  "category": "scientific_analysis",
  "content": "Detailed planning guidance...",
  "score": 5
}
```

Required in practice:

- `name`
- `description`
- `content`

Optional but useful:

- `category`
- `score`

The injected skill block does not include `score`.

## Complete Skill Injection Example

```yaml
upstream:
  base_url: "${UPSTREAM_BASE_URL}"
  api_key: "${UPSTREAM_API_KEY}"
  timeout_seconds: 900

auth:
  api_key: "${CONTEXT_OVERLAY_API_KEY}"

rules:
  - name: inject_solver_planning_skills
    match:
      path: "/v1/chat/completions"
      messages_regex:
        - "INSTRUCTIONS"
        - "report.md"
    transforms:
      - type: insert_before
        pattern: "Current date:"
        content:
          type: skill_dir
          path: "./skills/generated_skills"
          top_k: 5
          max_chars: 32000
          title: "Relevant Scientific Planning Skills"
```

Client:

```python
from openai import OpenAI

client = OpenAI(api_key="proxy-key", base_url="http://127.0.0.1:8011/v1")

response = client.chat.completions.create(
    model="Qwen3.5-9B",
    messages=[
        {"role": "system", "content": "You are a scientific agent.\n\nCurrent date: 2026-06-05"},
        {"role": "user", "content": "Here are the INSTRUCTIONS. Write report.md."},
    ],
)

print(response.choices[0].message.content)
```

## Public URL With cloudflared

Temporary public URL:

```bash
context-overlay serve --config config.yaml --host 127.0.0.1 --port 8011
cloudflared tunnel --url http://127.0.0.1:8011
```

Then set the SDK base URL to the generated URL plus `/v1`:

```python
from openai import OpenAI

client = OpenAI(
    api_key="proxy-key",
    base_url="https://your-random-subdomain.trycloudflare.com/v1",
)
```

Notes:

- Quick tunnel mode does not require a Cloudflare account.
- Quick tunnel mode does not require a domain.
- The URL is temporary and random.
- There is no uptime guarantee.
- For long-running production use, use a named Cloudflare Tunnel and an access policy.

## Python API

Public imports:

```python
import context_overlay
from context_overlay import ContextOverlayConfig, Skill, SkillStore, apply_rules, load_config
from context_overlay.server import create_app
```

### `context_overlay.__version__`

Package version string from installed package metadata.

```python
import context_overlay

print(context_overlay.__version__)
```

### `load_config(path)`

Load a YAML config file and return `ContextOverlayConfig`.

```python
from context_overlay import load_config

config = load_config("config.yaml")
```

### `ContextOverlayConfig`

Pydantic model for validated config.

```python
from context_overlay import ContextOverlayConfig

config = ContextOverlayConfig.model_validate(
    {
        "upstream": {"base_url": "http://127.0.0.1:8010/v1"},
        "rules": [],
    }
)
```

### `apply_rules(body, config, path="/v1/chat/completions")`

Apply matching rules and transforms to an OpenAI-compatible request body.

```python
from context_overlay import ContextOverlayConfig, apply_rules

config = ContextOverlayConfig.model_validate(
    {
        "upstream": {"base_url": "http://127.0.0.1:8010/v1"},
        "rules": [
            {
                "name": "append_overlay",
                "match": {"messages_regex": ["hello"]},
                "transforms": [{"type": "append_system", "content": "Injected."}],
            }
        ],
    }
)

body = {"model": "m", "messages": [{"role": "user", "content": "hello"}]}
new_body = apply_rules(body, config)

print(new_body["messages"][0])
```

### `create_app(config)`

Create a FastAPI app for embedding or custom serving.

```python
import uvicorn
from context_overlay import load_config
from context_overlay.server import create_app

config = load_config("config.yaml")
app = create_app(config)

uvicorn.run(app, host="127.0.0.1", port=8011)
```

### `Skill`

Dataclass representing a skill JSON file.

```python
from pathlib import Path
from context_overlay import Skill

skill = Skill.from_json_file(Path("skills/example.json"))
print(skill.name)
print(skill.description)
print(skill.content)
```

Fields:

- `path`
- `name`
- `description`
- `content`
- `category`
- `score`

### `SkillStore`

Load and retrieve skills from a directory.

```python
from context_overlay import SkillStore

store = SkillStore.from_dir("./skills/generated_skills")
skills = store.retrieve("glacier mass balance uncertainty", top_k=3)

for skill in skills:
    print(skill.name)
```

Retrieval is intentionally simple and deterministic:

- Tokenize query and skill text.
- Score by normalized lexical overlap.
- Return top-k skills.
- If the query has no tokens, return the first `top_k` skills in filename order.

## CLI

```bash
context-overlay serve --config config.yaml --host 127.0.0.1 --port 8011
```

Equivalent module form:

```bash
python -m context_overlay.cli serve --config config.yaml --host 127.0.0.1 --port 8011
```

CLI options:

- `--config`: YAML config path. Required.
- `--host`: bind host. Default: `127.0.0.1`.
- `--port`: bind port. Default: `8011`.
- `--reload`: enable uvicorn reload.

## Forwarding Behavior

`context-overlay` forwards all `/v1/*` paths to the upstream.

Special behavior only applies to:

```text
POST /v1/chat/completions
```

For that endpoint:

1. Parse JSON body.
2. Apply matching rules and transforms.
3. Forward the transformed request to the upstream.
4. Return the upstream response.

For other `/v1/*` endpoints, request content is forwarded without rule transforms.

Streaming requests are supported by forwarding upstream streaming bytes.

## Runtime Logs

Every `POST /v1/chat/completions` request emits one structured overlay decision
log line through uvicorn's normal logs.

When no rule matches:

```text
context_overlay event=no_rule_matched path=/v1/chat/completions model=gpt-5.5 rules_checked=40
```

When a rule matches:

```text
context_overlay event=rule_matched path=/v1/chat/completions model=gpt-5.5 rule=inject_Earth_000_planning_skill transform_count=1 transforms=type=insert_before;target=system;pattern=yes;content=file:/path/to/rendered_skill.md
```

The log format is intentionally key-value style:

- `event`: `rule_matched` or `no_rule_matched`.
- `path`: request path.
- `model`: request model field.
- `rule`: matched rule name, only present for `rule_matched`.
- `rules_checked`: total configured rule count, only present for `no_rule_matched`.
- `transform_count`: number of transforms in the matched rule.
- `transforms`: compact transform summaries, including transform type, target, pattern usage, route marker, and content source.

Content source summaries are safe and structural:

- Inline string content is logged as `content=inline_text`.
- File content is logged as `content=file:/path/to/file`.
- Skill directory content is logged as `content=skill_dir:/path:top_k=N`.
- Missing content is logged as `content=none`.

## Security Notes

- Use `auth.api_key` before exposing the proxy publicly.
- Keep upstream API keys on the server side.
- Do not put secrets in skill files or prompt overlays.
- Do not expose a proxy that can route to private internal services unless you trust the clients.
- Set upstream and client-side timeouts appropriate for your deployment.

## Development

```bash
pip install -e ".[dev]"
pytest -q
python -m build
python -m twine check dist/*
```

Local private configs or data can be kept under paths whose names start with
`local_`, for example `local_rcb_skills/` or `examples/local_config.yaml`.
These are ignored by git and should not be used for public examples. Public
examples should stay under `examples/` without private paths, API keys, internal
IP addresses, or user-specific data.

PyPI release is handled by GitHub Actions on published GitHub releases. The
workflow expects repository secret:

```text
PYPI_API_TOKEN
```
