#!/usr/bin/env python3
"""
Fake AI agent: sends one MCP JSON-RPC request to an HTTP MCP server through
the MayAI mitmproxy (default 127.0.0.1:8080) with X-Agent-ID / X-Agent-Token.

    python tests/test_agent_client.py tools/list
    python tests/test_agent_client.py tools/call echo -a text=hi
    python tests/test_agent_client.py tools/call echo -a "text=my password is 1234"
    python tests/test_agent_client.py tools/call echo --token wrong
    python tests/test_agent_client.py tools/list --target 127.0.0.1:9101
    python tests/test_agent_client.py tools/list --no-proxy     # straight to the server
    python tests/test_agent_client.py tools/call echo -a text=hi --stdio test-server   # STDIO transport
    python tests/test_agent_client.py tools/call fetch_page -a page=evil
    python tests/test_agent_client.py resources/read file:///docs/notes.md
    python tests/test_agent_client.py prompts/get summarize -a topic=revenue

Talks to the proxy with http.client directly, so OS proxy-bypass rules for
localhost cannot silently skip MayAI. Stdlib only.
"""

import argparse
import http.client
import json
import os
import subprocess
import sys
from pathlib import Path


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("method", help="JSON-RPC method, e.g. tools/list, tools/call, initialize")
    p.add_argument("tool", nargs="?",
                   help="tool name (tools/call), resource uri (resources/read) or prompt name (prompts/get)")
    p.add_argument("--args", default="{}", help="tool arguments as JSON")
    p.add_argument("-a", "--arg", action="append", default=[], metavar="KEY=VALUE",
                   help="one string tool argument (repeatable; easier than --args in PowerShell)")
    p.add_argument("--agent", default="agent-001")
    p.add_argument("--token", default="secret")
    p.add_argument("--target", default="127.0.0.1:9100", help="MCP server host:port")
    p.add_argument("--path", default="/mcp", help="HTTP endpoint path and optional query")
    p.add_argument("--timeout", type=float, default=120, help="response timeout in seconds")
    p.add_argument("--proxy", default="127.0.0.1:8080", help="MayAI mitmproxy host:port")
    p.add_argument("--no-proxy", action="store_true")
    p.add_argument("--id", type=int, default=1)
    p.add_argument("--stdio", metavar="SERVER_NAME",
                   help="STDIO mode: launch 'MayAI.py stdio --server-name SERVER_NAME' wrapping "
                        "'test_mcp_server.py --stdio' (policy target = stdio:SERVER_NAME)")
    p.add_argument("--rugpull", action="store_true", help="STDIO mode: start the server with --rugpull")
    p.add_argument("--poison", action="store_true", help="STDIO mode: start the server with --poison")
    o = p.parse_args()
    if o.timeout <= 0:
        p.error("--timeout must be positive")
    if not o.path.startswith("/") or o.path.startswith("//"):
        p.error("--path must start with a single /")

    params: dict = {}
    try:
        arguments = json.loads(o.args)
    except json.JSONDecodeError:
        p.error("--args must be a JSON object")
    if not isinstance(arguments, dict):
        p.error("--args must be a JSON object")
    for item in o.arg:
        key, sep, value = item.partition("=")
        if not sep or not key:
            p.error("-a expects KEY=VALUE")
        arguments[key] = value
    if o.method in ("tools/call", "prompts/get"):
        if not o.tool:
            p.error(f"{o.method} needs a name")
        params = {"name": o.tool, "arguments": arguments}
    elif o.method == "resources/read":
        if not o.tool:
            p.error("resources/read needs a resource uri")
        params = {"uri": o.tool}
    body = json.dumps({"jsonrpc": "2.0", "id": o.id, "method": o.method, "params": params})
    headers = {"Content-Type": "application/json", "Accept": "application/json",
               "X-Agent-ID": o.agent, "X-Agent-Token": o.token}

    try:
        if o.stdio:
            flags = [flag for flag, enabled in (("--rugpull", o.rugpull), ("--poison", o.poison)) if enabled]
            reply = stdio_exchange(o.agent, o.token, o.stdio, body, o.id, timeout=o.timeout, flags=flags)
            status = "OK" if reply_ok(reply, o.id) else "ERROR"
            print(f"STDIO {status}")
            print(json.dumps(reply, ensure_ascii=False, indent=2))
            return 0 if status == "OK" else 1

        address = o.target if o.no_proxy else o.proxy
        host, port = address.rsplit(":", 1)
        path = o.path if o.no_proxy else f"http://{o.target}{o.path}"
        conn = http.client.HTTPConnection(host, int(port), timeout=o.timeout)
        try:
            conn.request("POST", path, body, headers)
            resp = conn.getresponse()
            text = resp.read().decode("utf-8", "replace")
            print(f"HTTP {resp.status}")
            try:
                reply = json.loads(text)
            except json.JSONDecodeError:
                print(text)
                return 1
            print(json.dumps(reply, ensure_ascii=False, indent=2))
            return 0 if resp.status < 400 and reply_ok(reply, o.id) else 1
        finally:
            conn.close()
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as exc:
        print(f"테스트 요청 실패: {exc}", file=sys.stderr)
        return 1


def reply_ok(reply: object, request_id: int) -> bool:
    return isinstance(reply, dict) and reply.get("id") == request_id and "result" in reply and "error" not in reply


def stdio_exchange(agent: str, token: str, server_name: str, body: str, request_id: int, *,
                   timeout: float = 120, flags: tuple[str, ...] | list[str] = ()) -> dict:
    here = Path(__file__).resolve().parent
    server = [sys.executable, str(here / "test_mcp_server.py"), "--stdio", *flags]
    cmd = [sys.executable, str(here.parent / "MayAI.py"), "stdio", "--server-name", server_name, "--", *server]
    env = dict(os.environ, MAYAI_AGENT_ID=agent, MAYAI_AGENT_TOKEN=token)
    # Close stdin while collecting stdout. This also gives one-shot Windows
    # clients a finite timeout when response inspection is slow.
    proc = subprocess.run(cmd, input=(body + "\n").encode("utf-8"), capture_output=True, env=env, timeout=timeout)
    unmatched = None
    for line in proc.stdout.splitlines():
        if not line.strip():
            continue
        message = json.loads(line)
        if isinstance(message, dict) and "id" in message and "method" not in message:
            if message["id"] == request_id:
                return message
            if unmatched is None:
                unmatched = message
    if unmatched is not None:
        return unmatched
    raise RuntimeError(f"STDIO 응답이 없습니다. {proc.stderr.decode('utf-8', 'replace').strip()}")


if __name__ == "__main__":
    sys.exit(main())
