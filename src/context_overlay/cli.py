from __future__ import annotations

import argparse

import uvicorn

from .config import load_config
from .server import create_app


def main() -> None:
    parser = argparse.ArgumentParser(prog="context-overlay")
    subparsers = parser.add_subparsers(dest="command", required=True)

    serve_parser = subparsers.add_parser("serve", help="Run the OpenAI-compatible context overlay proxy")
    serve_parser.add_argument("--config", required=True, help="Path to YAML config")
    serve_parser.add_argument("--host", default="127.0.0.1")
    serve_parser.add_argument("--port", type=int, default=8011)
    serve_parser.add_argument("--reload", action="store_true")

    args = parser.parse_args()
    if args.command == "serve":
        config = load_config(args.config)
        app = create_app(config)
        uvicorn.run(app, host=args.host, port=args.port, reload=args.reload)
