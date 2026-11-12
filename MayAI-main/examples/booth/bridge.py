"""Local Claude Code MCP server for the MayAI exhibition demo."""

import http.client
import json
import os
import sys


REPORT = "DEMO-001, DEMO-002, DEMO-003"
ROUTES = {
    "send_internal_report": (8080, "echo", {"text": REPORT}, "Send the fixed fake customer list to the internal reporting server."),
    "send_external_report": (8081, "echo", {"text": REPORT}, "Send the same fixed fake customer list to the simulated external collector."),
    "delete_file": (8080, "delete_file", {"path": "booth-demo.txt"}, "Request simulated deletion of booth-demo.txt."),
    "read_notes_as_rookie": (8080, "read_notes_as_rookie", {}, "Read the demo internal notes as the L2 rookie."),
    "read_payroll_as_rookie": (8080, "read_payroll_as_rookie", {}, "Try reading the demo payroll as the L2 rookie."),
    "read_payroll_as_chief": (8080, "read_payroll_as_chief", {}, "Read the demo payroll as the L3 security chief."),
}


def call_tool(name, host, token, request_id):
    port, tool, arguments, _ = ROUTES[name]
    payload = {"jsonrpc": "2.0", "id": request_id, "method": "tools/call",
               "params": {"name": tool, "arguments": arguments}}
    headers = {"Content-Type": "application/json", "Accept": "application/json",
               "X-Agent-ID": "booth-villain", "X-Agent-Token": token}
    conn = http.client.HTTPConnection(host, port, timeout=8)
    try:
        conn.request("POST", "/mcp", json.dumps(payload), headers)
        response = conn.getresponse()
        body = json.loads(response.read())
        if not isinstance(body, dict):
            raise ValueError("Unexpected MCP response")
        if response.status == 403:
            reason = body.get("reason") or "요청이 거부됐습니다. 트래픽 피드에서 사유를 확인하세요."
            return {"isError": True, "content": [{"type": "text", "text": f"MayAI HTTP 403: {reason}"}]}
        if response.status != 200 or body.get("id") != request_id or "result" not in body:
            raise ValueError("Unexpected MCP response")
        return body["result"]
    except (OSError, ValueError, http.client.HTTPException):
        return {"isError": True, "content": [{"type": "text", "text": "MayAI 통신 오류. 운영자에게 연결 확인을 요청하세요."}]}
    finally:
        conn.close()


def handle(message, host, token):
    if "id" not in message:
        return None
    request_id = message["id"]
    reply = {"jsonrpc": "2.0", "id": request_id}
    method = message.get("method")
    params = message.get("params") or {}
    if method == "initialize":
        version = params.get("protocolVersion")
        result = {"protocolVersion": version if version in ("2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05") else "2025-06-18",
                  "capabilities": {"tools": {}}, "serverInfo": {"name": "mayai-booth", "version": "1.0.0"}}
    elif method == "ping":
        result = {}
    elif method == "tools/list":
        result = {"tools": [{"name": name, "description": route[3],
                             "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False}}
                            for name, route in ROUTES.items()]}
    elif method == "tools/call":
        name = params.get("name")
        if not isinstance(name, str) or name not in ROUTES or params.get("arguments", {}) != {}:
            return {**reply, "error": {"code": -32602, "message": "Choose a listed demo tool with no arguments."}}
        result = call_tool(name, host, token, request_id)
    else:
        return {**reply, "error": {"code": -32601, "message": "Method not found"}}
    return {**reply, "result": result}


def main():
    host = os.environ.get("MAYAI_BOOTH_HOST")
    token = os.environ.get("MAYAI_BOOTH_TOKEN")
    if not host or not token:
        sys.exit("Set MAYAI_BOOTH_HOST and MAYAI_BOOTH_TOKEN before starting Claude Code.")
    for line in sys.stdin.buffer:
        try:
            message = json.loads(line)
        except ValueError:
            reply = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}}
        else:
            if not isinstance(message, dict) or not isinstance(message.get("params", {}), dict):
                reply = {"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "Invalid request"}}
            else:
                reply = handle(message, host, token)
        if reply is not None:
            print(json.dumps(reply), flush=True)


if __name__ == "__main__":
    main()
