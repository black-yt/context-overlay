# context-overlay

`context-overlay` is an OpenAI-compatible request proxy that injects additional context into chat-completion requests without changing the upstream model server.

It can be used for:

- skill injection from local JSON skills
- prompt overlays and prompt patches
- policy or profile insertion
- lightweight request routing
- public demos through tools such as `ngrok` or `cloudflared`

The package does not run an agent loop and does not execute tools. It only transforms OpenAI-compatible HTTP requests and forwards them to an upstream OpenAI-compatible endpoint.

## Install

```bash
pip install context-overlay
```

For local development:

```bash
pip install -e ".[dev]"
```

## Quick Start

Create `config.yaml`:

```yaml
upstream:
  base_url: "http://127.0.0.1:8010/v1"
  api_key: "unused"

auth:
  api_key: "proxy-key"

rules:
  - name: inject_science_skills
    match:
      path: "/v1/chat/completions"
      messages_regex:
        - "scientific"
    transforms:
      - type: append_system
        content:
          type: skill_dir
          path: "./skills/generated_skills"
          top_k: 3
          max_chars: 24000
```

Run:

```bash
context-overlay serve --config config.yaml --host 127.0.0.1 --port 8011
```

Use it with the OpenAI SDK:

```python
from openai import OpenAI

client = OpenAI(api_key="proxy-key", base_url="http://127.0.0.1:8011/v1")

response = client.chat.completions.create(
    model="Qwen3.5-9B",
    messages=[{"role": "user", "content": "Analyze this scientific task."}],
)

print(response.choices[0].message.content)
```

## Public URL With ngrok

```bash
context-overlay serve --config config.yaml --host 127.0.0.1 --port 8011
ngrok http 8011
```

Then set the SDK base URL to the public ngrok URL plus `/v1`.

## Public URL With cloudflared

Temporary URL:

```bash
context-overlay serve --config config.yaml --host 127.0.0.1 --port 8011
cloudflared tunnel --url http://127.0.0.1:8011
```

Long-running production use should use a named Cloudflare Tunnel and your own access policy.

## Rule Model

Each rule has:

- `match`: decides whether a request should be transformed.
- `transforms`: one or more operations applied to the request body before forwarding.

Supported match fields:

- `path`
- `model_regex`
- `messages_regex`
- `extra_body`

Supported transform types:

- `prepend_system`
- `append_system`
- `insert_before`
- `insert_after`
- `regex_replace`
- `prepend_user`
- `append_user`
- `route`
- `reject`

Skill injection is implemented as a content source, not a special runtime mode.

## Security Notes

- Use `auth.api_key` before exposing the proxy publicly.
- Keep upstream API keys on the server side.
- Do not put secrets in skill files or prompt overlays.
- Set upstream and client-side timeouts appropriate for your deployment.
