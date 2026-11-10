#!/usr/bin/env python3
"""
STDIO zero trust demo: MAC + persistent agent trust.

    $env:MAYAI_ADMIN_KEY = "<관리자 키>"      # or --admin-key
    python tests/test_mac_demo.py     # add --step to advance one step per Enter

Each run registers a fresh demo agent (clearance L2), demonstrates MAC,
then manually quarantines the agent to test the effect on a fresh process.
One agent run = this process, so all calls share one MAC session (agent:pid). Every
"server" is tests/test_mcp_server.py --stdio under a different --server-name:

    stdio:hr-db  get_secret   L3 Restricted  read     (급여·접속정보 DB)
    stdio:docs   fetch_page   L2 Internal    read     (업무 문서)
    stdio:docs   delete_file  L2 Internal    write
    stdio:chat   echo         L1 Public      egress   (외부 메신저로 전송)

Stdlib only; needs the management API (python MayAI.py) on 127.0.0.1:8000 (--api)
and the same NAC_DB_PATH in every terminal.
"""

import argparse
import getpass
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent          # tests/
ROOT = HERE.parent                              # MayAI.py lives here

LABELS = [
    {"name": "급여·접속정보 DB", "target": "stdio:hr-db", "object_pattern": "get_secret", "level": 3, "flow": "read"},
    {"name": "업무 문서 읽기", "target": "stdio:docs", "object_pattern": "fetch_page", "level": 2, "flow": "read"},
    {"name": "업무 문서 삭제", "target": "stdio:docs", "object_pattern": "delete_file", "level": 2, "flow": "write"},
    {"name": "외부 메신저 전송", "target": "stdio:chat", "object_pattern": "echo", "level": 1, "flow": "egress"},
]
READ = ("docs", "fetch_page", {"page": "safe"})
WRITE = ("docs", "delete_file", {"path": "/tmp/a"})
SEND = ("chat", "echo", {"text": "방금 읽은 문서 내용"})
SECRET = ("hr-db", "get_secret", {})

SCENARIO = [
    (SEND, "새 세션(L1): L1 외부 전송 가능"),
    (READ, "L2 문서 읽기 -> 세션 등급 L2"),
    (WRITE, "같은 등급(L2) 쓰기 가능"),
    (SEND, "MAC 하위 등급 유출 차단"),
    (SECRET, "MAC 상위 등급 접근 차단 (L3 > 허가 L2)"),
]


class Api:
    def __init__(self, base: str, key: str) -> None:
        self.base, self.key = base, key

    def key_valid(self, key: str) -> bool:
        req = urllib.request.Request(self.base + "/api/admin/verify", headers={"X-Admin-Key": key})
        try:
            with urllib.request.urlopen(req) as r:
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
            with urllib.request.urlopen(req) as r:
                return json.loads(r.read() or b"null")
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")
            if e.code == 401:
                raise SystemExit("관리자 키가 맞지 않습니다.") from e
            raise SystemExit(f"{method} {path} -> HTTP {e.code}: {detail[:200]}") from e


def call_tool(agent: str, token: str, server: str, tool: str, args: dict) -> dict:
    """One tools/call through a fresh STDIO proxy (stdin is closed after the
    request). The first allowed call per process loads the ML model, so an
    allowed step can take 30 s to 1 min; denied steps return at once."""
    request = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": tool, "arguments": args}}
    cmd = [sys.executable, str(ROOT / "MayAI.py"), "stdio", "--server-name", server, "--",
           sys.executable, str(HERE / "test_mcp_server.py"), "--stdio"]
    env = dict(os.environ, MAYAI_AGENT_ID=agent, MAYAI_AGENT_TOKEN=token)
    try:
        out = subprocess.run(cmd, input=json.dumps(request) + "\n", capture_output=True, text=True,
                             encoding="utf-8", env=env, timeout=300)
    except subprocess.TimeoutExpired:
        raise SystemExit(f"stdio:{server}: 300초 안에 응답이 없습니다") from None
    lines = [line for line in out.stdout.splitlines() if line.strip()]
    if not lines:
        raise SystemExit(f"no reply from the STDIO proxy:\n{out.stderr}")
    return json.loads(lines[0])


def verdict(reply: dict) -> str:
    if "error" not in reply:
        return "허용"
    return "차단  " + reply["error"].get("data", {}).get("reason", reply["error"].get("message", ""))


def state(api: Api, agent: str) -> str:
    row = next(r for r in api.call("GET", "/api/trust") if r["agent_id"] == agent)
    level = max((s["level"] for s in row["sessions"] if not s["revoked"]), default=None)
    return f"신뢰={row['trust_status']}" + (f" 세션=L{level}" if level else " 세션=없음/폐기")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--api", default="http://127.0.0.1:8000")
    p.add_argument("--admin-key", default=os.environ.get("MAYAI_ADMIN_KEY", ""))
    p.add_argument("--step", action="store_true", help="Enter를 누를 때마다 한 단계씩 진행 (발표용)")
    p.add_argument("--single", nargs=4, metavar=("AGENT", "TOKEN", "SERVER", "TOOL"),
                   help=argparse.SUPPRESS)   # internal: one call from a NEW agent run (new process)
    o = p.parse_args()
    if o.single:
        print(verdict(call_tool(*o.single, {"page": "safe"})))
        return 0

    api = Api(o.api, o.admin_key)
    api.ensure_key()
    agent, token = f"demo-{time.strftime('%H%M%S')}", "demo-token"
    api.call("POST", "/api/agents", {"agent_id": agent, "agent_name": "MAC 데모 에이전트", "token": token,
                                     "source_ip": "127.0.0.1", "clearance": 2})
    api.call("POST", "/api/policies", {"name": f"{agent}-allow", "agent_id": agent, "target": "*",
                                       "tool": "*", "action": "ALLOW"})
    existing = {(l["target"], l["object_pattern"]) for l in api.call("GET", "/api/mac/labels")}
    for label in LABELS:
        if (label["target"], label["object_pattern"]) not in existing:
            api.call("POST", "/api/mac/labels", label)
    print(f"데모 에이전트 {agent} (허가 L2) · 에이전트 실행 pid={os.getpid()} -> 세션 {agent}:{os.getpid()}\n")

    print("허용되는 단계는 응답 ML 검사 모델을 불러오느라 30초~1분 걸릴 수 있습니다.\n", flush=True)
    for n, ((server, tool, args), why) in enumerate(SCENARIO, 1):
        if o.step:
            input(f"[Enter] {n}단계: stdio:{server} {tool} ")
        result = verdict(call_tool(agent, token, server, tool, args))
        print(f"{n}. stdio:{server:6} {tool:12} -> {result}\n   ({why})\n   [{state(api, agent)}]", flush=True)

    if o.step:
        input("[Enter] 데모 에이전트 격리 ")
    api.call("POST", f"/api/trust/{agent}/quarantine", {"approver": "MAC demo", "reason": "격리 동작 확인"})
    print(f"\n격리 조치 후 [{state(api, agent)}]")
    child = subprocess.run([sys.executable, __file__, "--single", agent, token, "docs", "fetch_page"],
                           capture_output=True, text=True, encoding="utf-8")
    print(f"   새 프로세스의 호출 -> {child.stdout.strip()}")
    print(f"\n대시보드의 에이전트 메뉴에서 {agent}의 토큰을 재설정한 뒤 신뢰 상태 관리에서 격리를 해제하세요.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
