#!/usr/bin/env python3
"""
STDIO MAC and quarantine demo against a running MayAI management API.

    python tests/test_mac_demo.py         # add --step to pause before each call

Use the same NAC_DB_PATH and MAYAI_ADMIN_KEY as the management server.
Each run creates its own agent, registered servers, and typed MAC labels.
"""

import argparse
import getpass
import json
import os
import subprocess
import sys
import uuid
import urllib.error
import urllib.request
from pathlib import Path

from test_agent_client import reply_ok, stdio_exchange

HERE = Path(__file__).resolve().parent          # tests/
# Alias, object type, name or URI, level, and data flow.
LABELS = [
    ("hr-db", "tool", "get_secret", 3, "read"),
    ("docs", "tool", "fetch_page", 2, "read"),
    ("docs", "tool", "delete_file", 2, "write"),
    ("docs", "resource", "file:///docs/readme.md", 2, "read"),
    ("docs", "prompt", "code_review", 2, "read"),
    ("chat", "tool", "echo", 1, "egress"),
]
# Alias, method, identifier, arguments, expected session level, and denial reason.
SCENARIO = [
    ("chat", "tools/call", "echo", {"text": "공개 자료"}, 1, ""),
    ("docs", "resources/read", "file:///docs/readme.md", {}, 2, ""),
    ("docs", "prompts/get", "code_review", {"diff": "+ print(1)"}, 2, ""),
    ("docs", "tools/call", "delete_file", {"path": "/tmp/a"}, 2, ""),
    ("chat", "tools/call", "echo", {"text": "방금 읽은 문서"}, 2, "leak it down"),
    ("hr-db", "tools/call", "get_secret", {}, 2, "above agent clearance"),
    ("docs", "tools/call", "code_review", {}, 2, "unlabeled"),
]


class Api:
    def __init__(self, base: str, key: str) -> None:
        self.base, self.key = base, key

    def key_valid(self, key: str) -> bool:
        req = urllib.request.Request(self.base + "/api/admin/verify", headers={"X-Admin-Key": key})
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return json.loads(r.read()).get("valid") is True
        except urllib.error.HTTPError as e:
            if e.code == 404:
                raise SystemExit("서버가 이전 버전입니다. python MayAI.py 를 재시작하세요.") from e
            raise
        except urllib.error.URLError as e:
            raise SystemExit(f"관리 API({self.base})에 연결할 수 없습니다. python MayAI.py 가 실행 중인가요?") from e

    def ensure_key(self) -> None:
        """The dashboard keeps its key in the browser; this script needs its own.
        Use MAYAI_ADMIN_KEY / --admin-key, or type it here (input hidden)."""
        if self.key and self.key_valid(self.key):
            return
        if self.key:
            print("MAYAI_ADMIN_KEY(또는 --admin-key) 값이 서버의 관리자 키와 다릅니다.")
        else:
            print("관리자 키가 필요합니다. (대시보드에 입력한 키는 브라우저에만 저장되어 이 스크립트는 볼 수 없습니다)")
        for _ in range(3):
            key = getpass.getpass("관리자 키 입력 (화면에 표시되지 않음): ").strip()
            if key and self.key_valid(key):
                self.key = key
                return
            print("맞지 않는 키입니다.")
        raise SystemExit("관리자 키 확인 실패. 서버를 띄운 터미널의 MAYAI_ADMIN_KEY 값이나 처음 실행 때 콘솔에 표시된 키를 쓰세요.")

    def call(self, method: str, path: str, body: dict | None = None):
        req = urllib.request.Request(self.base + path, method=method,
                                     data=json.dumps(body).encode() if body is not None else None,
                                     headers={"Content-Type": "application/json", "X-Admin-Key": self.key})
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return json.loads(r.read() or b"null")
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")
            if e.code == 401:
                raise SystemExit("관리자 키가 맞지 않습니다.") from e
            raise SystemExit(f"{method} {path} -> HTTP {e.code}: {detail[:200]}") from e


def call_object(agent: str, token: str, server: str, method: str, identifier: str, args: dict) -> dict:
    params = {"uri": identifier} if method == "resources/read" else {"name": identifier, "arguments": args}
    request = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
    return stdio_exchange(agent, token, server, json.dumps(request), 1)


def denial_reason(reply: dict) -> str:
    error = reply.get("error", {})
    return error.get("data", {}).get("reason", error.get("message", ""))


def agent_state(api: Api, agent: str) -> dict:
    return next(row for row in api.call("GET", "/api/trust") if row["agent_id"] == agent)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--api", default="http://127.0.0.1:8000")
    p.add_argument("--admin-key", default=os.environ.get("MAYAI_ADMIN_KEY", ""))
    p.add_argument("--step", action="store_true", help="Enter를 누를 때마다 한 단계씩 진행 (발표용)")
    o = p.parse_args()
    api = Api(o.api, o.admin_key)
    api.ensure_key()

    agent, token = f"demo-{uuid.uuid4().hex[:8]}", "demo-token"
    api.call("POST", "/api/agents", {"agent_id": agent, "agent_name": "MAC 데모 에이전트", "token": token,
                                     "source_ip": "127.0.0.1", "clearance": 2})
    api.call("POST", "/api/policies", {"name": f"{agent}-allow", "agent_id": agent, "target": "*",
                                       "mcp_method": "*", "tool": "*", "action": "ALLOW"})
    servers = {}
    for alias, kind, identifier, level, flow in LABELS:
        if alias not in servers:
            name = f"{agent}-{alias}"
            created = api.call("POST", "/api/mcp/servers", {"name": name, "stdio_target": name})
            servers[alias] = (name, created["server_id"])
        api.call("POST", "/api/mac/labels", {"name": f"{agent} {identifier}", "server_id": servers[alias][1],
                                             "object_type": kind, "object_pattern": identifier,
                                             "level": level, "flow": flow})

    session_id = None
    known_sessions = set()
    print(f"데모 에이전트 {agent} (허가 L2)", flush=True)
    try:
        for n, (alias, method, identifier, args, expected_level, expected_denial) in enumerate(SCENARIO, 1):
            server, server_id = servers[alias]
            if o.step:
                input(f"[Enter] {n}단계 {method} {identifier} ")
            reply = call_object(agent, token, server, method, identifier, args)
            reason = denial_reason(reply)
            if expected_denial:
                if expected_denial not in reason or reply.get("error", {}).get("code") != -32003:
                    raise RuntimeError(f"{n}단계에서 예상한 MAC 차단이 발생하지 않았습니다. {reply}")
            elif not reply_ok(reply, 1):
                raise RuntimeError(f"{n}단계에서 허용을 기대했습니다. {reply}")

            sessions = {s["session_id"]: s for s in agent_state(api, agent)["sessions"]}
            # A Windows Python launcher can give each proxy a different parent
            # PID. In that case the new session inherits the previous level.
            new_sessions = sessions.keys() - known_sessions
            if len(new_sessions) == 1:
                session_id = new_sessions.pop()
            known_sessions.update(sessions)
            session = sessions.get(session_id)
            if not session or session["level"] != expected_level or session["revoked"]:
                raise RuntimeError(f"{n}단계에서 세션 등급 L{expected_level}을 기대했습니다. {session}")
            logs = api.call("GET", "/api/logs?limit=50")
            latest = next((row for row in logs if row["agent_id"] == agent and row["direction"] == "outbound"), None)
            if not latest or latest["server_id"] != server_id:
                raise RuntimeError(f"{n}단계에서 등록 서버 #{server_id} 기록을 찾지 못했습니다.")
            print(f"{n}. {method} {identifier} · 서버 #{server_id} · 세션 {session_id} L{expected_level} · {reason or '허용'}",
                  flush=True)

        if o.step:
            input("[Enter] 데모 에이전트 격리 ")
        api.call("POST", f"/api/trust/{agent}/quarantine", {"approver": "MAC demo", "reason": "격리 동작 확인"})
        state = agent_state(api, agent)
        if state["trust_status"] != "COMPROMISED" or any(not s["revoked"] for s in state["sessions"]):
            raise RuntimeError("격리 상태와 세션 폐기를 확인하지 못했습니다.")
        child = subprocess.run(
            [sys.executable, str(HERE / "test_agent_client.py"), "tools/list", "--stdio", servers["docs"][0],
             "--agent", agent, "--token", token], capture_output=True, encoding="utf-8",
            env=dict(os.environ, PYTHONIOENCODING="utf-8"), timeout=130,
        )
        if child.returncode != 1 or "agent quarantined" not in child.stdout:
            raise RuntimeError(f"새 프로세스의 요청이 격리로 차단되지 않았습니다. {child.stdout} {child.stderr}")
    except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired) as exc:
        print(f"MAC 데모 실패: {exc}", file=sys.stderr)
        return 1

    print(f"MAC 데모 통과 · 에이전트 {agent} 격리 및 새 프로세스 차단 확인")
    print("격리 해제를 확인하려면 대시보드에서 이 에이전트의 토큰을 교체하고 조치 내용을 입력하세요.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
