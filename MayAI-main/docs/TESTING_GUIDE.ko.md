# MayAI 테스트 가이드 (Windows / 로컬 단일 PC)

Windows 한 대에서 HTTP(S) 프록시와 STDIO 프록시를 테스트합니다. 요청·응답 정책, 공통 MCP 서버 식별, STDIO MAC, 에이전트 격리를 순서대로 확인할 수 있습니다.

```
[tests/test_agent_client.py] --X-Agent-ID/Token--> [mitmdump :8080 + MayAI.py] --> [test_mcp_server.py :9100]
                                                    |
                                   nac.db  <--  [관리 API/대시보드 :8000]
```

> 모든 명령은 `MayAI-main` 폴더에서 실행합니다.

## 0. 준비

```powershell
python --version
python -m pip install fastapi uvicorn mitmproxy httpx2
```

- `httpx2`는 `--selftest`의 API 테스트(`fastapi.testclient`)에만 필요합니다.
- ML 패키지(`requirements-ml.txt`)는 선택 사항입니다 (7장).

**테스트용 DB 분리 (권장)** — 기존 `nac.db`를 건드리지 않으려면, 사용하는 **모든 터미널**에서:

```powershell
$env:NAC_DB_PATH = "$env:TEMP\nac-test.db"
$env:MAYAI_ADMIN_KEY = "test-admin-key"   # 관리자 키 (아래 설명)
```

관리 API, mitmdump, STDIO 클라이언트가 같은 DB 경로를 사용해야 합니다. 처음 실행할 때는 비어 있는 테스트 DB 경로를 사용하세요. 이전 테스트 DB를 쓰면 기존 에이전트와 정책이 결과에 영향을 줍니다.

**관리자 키** — 관리 API의 변경 요청(POST·PUT·PATCH·DELETE)은 전부 `X-Admin-Key` 헤더가 필요합니다(없거나 틀리면 401).
목록·요약은 키 없이 볼 수 있고, 요청·응답 **본문 원문 조회**에도 관리자 키가 필요합니다.
- `MAYAI_ADMIN_KEY`를 지정하고 서버를 띄우면 그 값이 키입니다.
- 지정하지 않으면 처음 실행할 때 키를 만들어 **콘솔에 한 번만** 출력합니다(DB에는 해시만 저장).
- 대시보드는 변경 작업 때 키를 물어보고 이 브라우저에만 저장합니다. 상단 **관리자 키** 버튼으로 바꿀 수 있습니다.
- 변경 기록은 **감사 로그** 탭에서 확인합니다.

## 1. 셀프 테스트

```powershell
python MayAI.py --selftest
# -> nac-proxy selftest: OK (all assertions passed)
```

셀프 테스트는 항상 `%TEMP%\nac-selftest.db`를 써서 실제 DB를 건드리지 않습니다.
`starlette.testclient ... requires the httpx2 package` 오류가 나면 `pip install httpx2`.

## 2. 테스트 환경 띄우기 (터미널 3개)

| 터미널 | 명령 | 역할 |
|---|---|---|
| A | `python tests/test_mcp_server.py --check-agent-headers` | 테스트 MCP 서버 `127.0.0.1:9100` |
| B | `python MayAI.py` | 관리 API + 대시보드 `http://127.0.0.1:8000/` |
| C | `mitmdump -s MayAI.py --listen-host 127.0.0.1 -p 8080` | 로컬 HTTP 트래픽 검사 프록시 |

- Swagger UI: http://127.0.0.1:8000/docs — 아래의 API 호출은 전부 여기서도 할 수 있습니다.
- 대시보드에서도 에이전트/정책 등록, 로그·이벤트 조회가 가능합니다.

`tests/test_mcp_server.py`의 도구:

| 도구 | 동작 | 확인 대상 |
|---|---|---|
| `echo` | 인자 그대로 반환 | 정상 흐름 |
| `get_secret` | `password=…, api_key=…` 반환 | `RESPONSE_SENSITIVE_DATA` |
| `weather` | `city=bad`면 outputSchema 위반 | `OUTPUT_SCHEMA_VIOLATION` |
| `bad_id` | 다른 JSON-RPC id로 응답 | `JSONRPC_ID_MISMATCH` |
| `delete_file` | 위험해 보이는 이름 | DENY 정책 연습 |
| (`--rugpull`로 재시작) | `echo` 설명이 바뀜 | `TOOL_DEFINITION_CHANGED` |

`tests/test_agent_client.py`의 기본값은 에이전트 `agent-001`, 토큰 `secret`, 서버 `127.0.0.1:9100`, 프록시 `127.0.0.1:8080`, HTTP 경로 `/mcp`입니다. 인자는 `-a key=value`로 넘기고, 경로는 `--path`로 바꿀 수 있습니다. 정상 JSON-RPC 결과는 종료 코드 0, 차단·오류·ID 불일치는 1을 반환합니다. `--check-agent-headers`를 켠 테스트 서버는 프록시가 에이전트 인증 헤더를 업스트림으로 전달하면 HTTP 400을 반환합니다.

## 3. 요청 정책 테스트 (기본 차단)

4번째 터미널(D)에서 진행합니다.

### 3-1. 미등록 에이전트 → 차단

```powershell
python tests/test_agent_client.py tools/list
# HTTP 403  "reason": "unregistered agent: agent-001"
```

### 3-2. 에이전트 등록

로컬 테스트에서는 mitmproxy가 보는 출발지 IP가 `127.0.0.1`이므로 `source_ip`도 그 값입니다.

```powershell
$api = "http://127.0.0.1:8000"
$h = @{ "X-Admin-Key" = $env:MAYAI_ADMIN_KEY }   # 변경 요청에 붙이는 관리자 키
$body = @{ agent_id="agent-001"; agent_name="Local Test Agent"; token="secret"; source_ip="127.0.0.1" } | ConvertTo-Json
Invoke-RestMethod -Method Post "$api/api/agents" -ContentType application/json -Body $body -Headers $h
```

```powershell
python tests/test_agent_client.py tools/list
# HTTP 403  "reason": "no matching policy (default deny)"   <- 인증 통과, 정책 없음
python tests/test_agent_client.py tools/list --token wrong
# HTTP 403  "reason": "invalid token"
```

### 3-3. 정책 추가 (ALLOW 전체 + 특정 도구 DENY)

HTTP(S) 정책에는 `destination_ip_port` 또는 `destination_url` 중 하나를 지정합니다. `mcp_method`는 MCP 메서드, `tool`은 도구 이름입니다. `*`는 전체 메서드 또는 전체 도구를 뜻합니다. 요청 정책은 DENY를 우선하고, 같은 동작에서는 더 구체적인 정책을 우선합니다.

```powershell
$p1 = @{ name="allow-mcp-all"; agent_id="agent-001"; destination_url="http://127.0.0.1:9100/mcp"; mcp_method="*"; tool="*"; action="ALLOW" } | ConvertTo-Json
$p2 = @{ name="deny-delete"; agent_id="agent-001"; destination_ip_port="127.0.0.1:9100"; mcp_method="tools/call"; tool="delete_file"; action="DENY" } | ConvertTo-Json
Invoke-RestMethod -Method Post "$api/api/policies" -ContentType application/json -Body $p1 -Headers $h
Invoke-RestMethod -Method Post "$api/api/policies" -ContentType application/json -Body $p2 -Headers $h
```

### 3-4. 결과 확인

| 명령 | 기대 결과 |
|---|---|
| `python tests/test_agent_client.py tools/list` | HTTP 200, 도구 목록 |
| `python tests/test_agent_client.py tools/call echo -a text=hello` | HTTP 200, `"hello"` |
| `python tests/test_agent_client.py tools/call delete_file -a path=/etc/passwd` | HTTP 403, `matched policy 'deny-delete'` |
| `python tests/test_agent_client.py tools/list --target 127.0.0.1:9101` | HTTP 403, 허용 URL과 포트 불일치 |
| `python tests/test_agent_client.py tools/list --path /other` | HTTP 403, 허용 URL과 경로 불일치 |
| `python tests/test_agent_client.py tools/list --agent ghost` | HTTP 403, unregistered agent |
| `python tests/test_agent_client.py tools/list --no-proxy` | HTTP 400, 테스트 서버가 에이전트 인증 헤더 유입 감지 |
| `python tests/test_agent_client.py tools/call echo -a "text=my password is 1234"` | HTTP 200 (허용) + 로그에 `SENSITIVE_DATA_EXPOSURE`, 위험도 상승 |

이 예제에서 요청 속 민감정보는 보안 이벤트로 기록됩니다. 요청 차단은 인증, 격리 상태, 요청 정책 및 STDIO의 MAC 판정에 따라 결정됩니다.

로그 확인 (PowerShell 5.1에서는 `Invoke-RestMethod`를 **괄호로 감싸야** 배열이 행 단위로 나옵니다):

```powershell
(Invoke-RestMethod "$api/api/logs?limit=10") | Format-Table log_id,agent_id,source,destination,tool,decision,reason
```

**관리자 결정으로 정책 추가**를 테스트할 때는 매칭 규칙이 없어 차단된 로그를 고릅니다. 예를 들어 위의 다른 경로 테스트 로그 ID를 사용합니다.

```powershell
Invoke-RestMethod -Method Post "$api/api/decisions/<log_id>" -ContentType application/json -Body '{"decision":"ALLOW","reason":"reviewed"}' -Headers $h
```

로그의 에이전트, 목적지, MCP 메서드, 도구 이름을 바탕으로 정책이 만들어집니다. 이 예제는 호스트와 포트에 대한 허용 규칙을 추가하므로, 이후 URL 경로 차단을 다시 확인하려면 추가한 정책을 삭제하세요.

## 4. 응답 정책 테스트 (MONITOR → ENFORCE)

응답 정책은 요청 정책과 별개이며 **기본 허용**, 초기 모드는 **MONITOR**(기록만)입니다.

```powershell
# (1) 정책 없음: 탐지만 기록
python tests/test_agent_client.py tools/call get_secret          # HTTP 200

# (2) 민감정보 응답 DENY 정책 추가 - MONITOR라 아직 통과, policy_action=DENY로 기록
$rp = @{ name="deny-resp-sensitive"; agent_id="agent-001"; mcp_method="tools/call"; tool="get_secret"; finding="RESPONSE_SENSITIVE_DATA"; action="DENY" } | ConvertTo-Json
Invoke-RestMethod -Method Post "$api/api/response-policies" -ContentType application/json -Body $rp -Headers $h
python tests/test_agent_client.py tools/call get_secret          # HTTP 200

# (3) ENFORCE 전환 → 실제 차단
Invoke-RestMethod -Method Put "$api/api/settings/response-enforcement" -ContentType application/json -Body '{"mode":"ENFORCE"}' -Headers $h
python tests/test_agent_client.py tools/call get_secret
# HTTP 403, JSON-RPC error.code=-32003, message="MayAI response blocked"
```

결과 비교:

```powershell
(Invoke-RestMethod "$api/api/responses") | Select-Object response_id,tool,@{n='findings';e={$_.findings -join ','}},policy_action,effective_action,enforcement_mode | Format-Table -AutoSize
```

`get_secret` 요청 3회의 결과 예시는 다음과 같습니다.

```
response_id tool       findings                 policy_action effective_action enforcement_mode
          6 get_secret RESPONSE_SENSITIVE_DATA  DENY          DENY             ENFORCE   <- 차단
          5 get_secret RESPONSE_SENSITIVE_DATA  DENY          ALLOW            MONITOR   <- 기록만
          4 get_secret RESPONSE_SENSITIVE_DATA  ALLOW         ALLOW            MONITOR
```

응답 정책에서 선택 가능한 탐지 항목은 **응답 정책** 탭과 관리 API의 Swagger UI에서 확인할 수 있습니다. `*`는 모든 탐지 항목을 뜻합니다.

응답 정책은 finding마다 따로 판정합니다 (더 구체적인 정책 → 동률이면 DENY).
이 테스트가 끝나면 이후 시나리오의 응답을 확인할 수 있도록 모니터링 모드로 되돌립니다.

```powershell
Invoke-RestMethod -Method Put "$api/api/settings/response-enforcement" -ContentType application/json -Body '{"mode":"MONITOR"}' -Headers $h
```

## 5. 탐지 시나리오

| 시나리오 | 명령 | 기대 finding / 이벤트 |
|---|---|---|
| JSON-RPC id 위조 | `python tests/test_agent_client.py tools/call bad_id` | `JSONRPC_ID_MISMATCH` (high) |
| outputSchema 위반 | `python tests/test_agent_client.py tools/call weather -a city=bad` | `OUTPUT_SCHEMA_VIOLATION` |
| inputSchema 위반 | 먼저 `tools/list` 1회 후 `python tests/test_agent_client.py tools/call weather` (city 누락) | 요청 쪽 `INPUT_SCHEMA_VIOLATION` |
| Rug-pull | `tools/list` 1회 → 터미널 A를 `python tests/test_mcp_server.py --check-agent-headers --rugpull`로 재시작 → `tools/list` 다시 | `TOOL_DEFINITION_CHANGED` (high) |

이벤트 확인:

```powershell
(Invoke-RestMethod "$api/api/events") | Select-Object -First 10 | Format-Table event_id,event_type,severity,target,reason
```

트래픽 탐색 (전송/방향/규칙 필터):

```powershell
(Invoke-RestMethod "$api/api/explore?direction=response&rule=TOOL_DEFINITION_CHANGED").rows
```

## 6. 실제 MCP 클라이언트로 테스트

### 6-1. HTTP MCP 서버 (mitmproxy 경유)

에이전트 **프로세스에만** 프록시를 지정하고, 모든 요청에 `X-Agent-ID` / `X-Agent-Token` 헤더를 넣어야 합니다.

```powershell
$env:HTTP_PROXY  = "http://127.0.0.1:8080"
$env:HTTPS_PROXY = "http://127.0.0.1:8080"
# 이 터미널에서 에이전트 실행
```

- **localhost 우회 주의**: 많은 HTTP 라이브러리가 `localhost`/`127.0.0.1` 대상이면 프록시를 건너뜁니다.
  로그에 아무것도 안 쌓이면 서버를 다른 IP로 띄우거나 `NO_PROXY`를 확인하세요.
- **HTTPS 대상**: 에이전트가 mitmproxy CA를 신뢰해야 합니다. mitmdump 실행 중 프록시를 거쳐
  http://mitm.it 에서 인증서를 받아 설치합니다 (테스트 PC에서만).
- **SSE 응답**(`text/event-stream`)은 검사하지 않고 `RESPONSE_STREAMING_SKIPPED`로 기록됩니다.
- **다른 PC의 에이전트**를 테스트하려면 mitmdump의 `--listen-host`를 게이트웨이의 접근 가능한 IP로 바꾸고, 에이전트 `source_ip`에는 프록시가 보는 클라이언트 IPv4를 등록합니다. 정책 목적지는 실제 MCP 서버 주소로 지정합니다.

### 6-2. 공통 MCP 서버 식별과 STDIO 테스트

`--stdio <서버이름>`은 테스트 클라이언트가 MayAI STDIO 프록시와 테스트 MCP 서버를 함께 실행하도록 합니다. STDIO만 확인할 때는 터미널 A와 C 없이 진행할 수 있습니다. 3장에서 등록한 에이전트와 같은 테스트 DB를 사용합니다.

```powershell
$server = Invoke-RestMethod -Method Post "$api/api/mcp/servers" -ContentType application/json -Headers $h -Body '{"name":"Local Test MCP","stdio_target":"test-server","http_url":"http://127.0.0.1:9100/mcp"}'
$stdioPolicy = @{ name="allow-test-stdio"; agent_id="agent-001"; target="stdio:test-server"; mcp_method="*"; tool="*"; action="ALLOW" } | ConvertTo-Json
Invoke-RestMethod -Method Post "$api/api/policies" -ContentType application/json -Body $stdioPolicy -Headers $h

python tests/test_agent_client.py tools/call echo -a text=hi --stdio test-server
# STDIO ERROR. 요청 상세의 탐지 항목은 MAC_READ_UP_DENY (허가 L2, 등급 미지정 L4)

$label = @{ name="test echo"; server_id=$server.server_id; object_type="tool"; object_pattern="echo"; level=2; flow="read" } | ConvertTo-Json
Invoke-RestMethod -Method Post "$api/api/mac/labels" -ContentType application/json -Body $label -Headers $h
python tests/test_agent_client.py tools/call echo -a text=hi --stdio test-server
# STDIO OK
python tests/test_agent_client.py tools/call echo -a text=hi
# HTTP 200 (터미널 A·C 실행 중)
```

대시보드에서는 **파일 접근 제어 → MCP 도구 접근 제어 → MCP 서버 등록 및 관리**에서 두 접속 정보를 등록합니다. **객체 등급 지정**에서 서버와 대상 유형 **도구**를 선택하고 `echo`를 입력합니다.

**트래픽 피드**에서 위 STDIO 및 HTTP 요청·응답의 상세를 열어 동일한 **등록 MCP 서버** 이름과 ID가 표시되는지 확인합니다. **본문 원문 보기**에는 관리자 키가 필요합니다. HTTP(S) 등록은 실제 요청 URL 전체와 비교하며, MAC 등급 판정과 세션 등급 갱신은 STDIO에서 수행합니다.

### 6-3. STDIO MCP 서버를 실제 클라이언트에 연결

MCP 클라이언트가 서버 대신 `MayAI.py stdio`를 실행하게 합니다 (`examples/mcp.json` 예시 참고).

1. 에이전트 등록: `agent_id="agent-stdio"`, `token="s3cret"`, **`source_ip="127.0.0.1"`** (STDIO는 항상 127.0.0.1)
2. 요청 정책에는 API에서 `target="stdio:everything"`, `mcp_method="*"`, `tool="*"`, `action="ALLOW"`를 지정합니다. **파일 접근 제어 → MCP 도구 접근 제어**에서 STDIO 실행 이름이 `everything`인 서버를 등록하고 필요한 도구에 등급과 흐름을 지정합니다.
3. 클라이언트 설정에 `examples/mcp.json`의 `mayai-everything` 항목 추가. `args`의 `MayAI.py`는 **절대 경로**로,
   DB를 분리했다면 `env`에 `NAC_DB_PATH`도 추가합니다.
4. 클라이언트에서 도구 사용 → `/api/logs`에서 `transport=stdio` 기록 확인

### 6-4. MAC 제로 트러스트 (STDIO 전용)

STDIO 요청은 요청 정책을 통과한 뒤 MAC 검사를 한 번 더 받습니다. 둘 다 통과해야 MCP 서버로 전달됩니다.

| 등급 | 분류 | 데이터 예시 |
|---|---|---|
| L4 | Critical (핵심기밀) | 암호화 키, 핵심 보안 정책, 최고관리자 인증정보 |
| L3 | Restricted (제한정보) | 개인정보, 내부 보안 로그, 중요 시스템 설정 |
| L2 | Internal (내부정보) | 업무 문서, 내부 운영 자료 |
| L1 | Public (공개정보) | 공개 문서, 대외 홍보 자료 |

- **에이전트 허가 등급**: 에이전트 탭에서 지정 (기본 L2)
- **대상 라벨**은 등록 서버, 대상 유형, 도구 이름·리소스 URI·프롬프트 이름으로 지정합니다. 이름 패턴도 같은 유형 안에서 적용됩니다. 라벨이 없으면 L4로 취급합니다.
- **규칙**: ① 허가 등급보다 높은 대상 접근 금지(`MAC_READ_UP_DENY`)
  ② 세션이 받은 데이터보다 낮은 등급 대상으로 쓰기·외부 전송 금지(`MAC_WRITE_DOWN_DENY`)
- **세션**은 에이전트 ID와 STDIO 프록시의 부모 프로세스 PID로 구분합니다. 같은 부모에서 실행한 프록시들은 세션을 공유합니다.
  세션 등급은 받은 데이터 등급만큼 올라가고(응답에 민감정보가 있으면 최소 L3), **새 세션(재시작·재인증)은
  직전 세션 등급을 이어받습니다** — 재시작으로 받은 데이터 이력을 지울 수 없게 하기 위해서입니다.
  관리자가 대시보드에서 **L1로 초기화**할 때만 내려갑니다.
- `tools/call`, `resources/read`, `prompts/get`만 검사합니다. `initialize`, `*/list`, 알림은 요청 정책만 적용.
- HTTP(mitmproxy) 경로에는 적용되지 않습니다.

### 6-5. 에이전트 격리 (HTTP(S)·STDIO)

**에이전트 → 신뢰 상태 관리**에서 상태와 격리 사유를 확인합니다.

| 상태 | HTTP(S)·STDIO 동작 |
|---|---|
| 정상 | 인증과 요청·응답 정책을 적용합니다. STDIO에서는 MAC도 적용합니다. |
| 격리됨 | 새 요청과 아직 전달되지 않은 응답을 차단합니다. 기존 STDIO 세션은 폐기합니다. |

탐지 결과는 보안 이벤트에서 확인합니다. 담당자가 격리 여부를 결정하며, 격리와 해제 조치는 감사 로그에 기록됩니다.
격리 원인을 제거하고 에이전트의 토큰을 재설정한 뒤, **격리 해제**에서 조치 내용을 기록하면 정상으로 돌아옵니다.
STDIO는 새 토큰으로 에이전트를 다시 실행합니다.
HTTP 검사와 격리 확인을 건너뛸 수 있는 mitmproxy의 자동 스트리밍 옵션 `stream_large_bodies`는 사용할 수 없습니다.

관리 API와 같은 테스트 DB·관리자 키를 사용하는 터미널에서 데모를 실행합니다. 데모는 자체 에이전트와 서버를 등록하고, 등록 서버 ID, 도구·리소스·프롬프트 규칙, 세션 등급 상승, 상·하위 등급 차단, 격리 후 재실행 차단을 검사합니다. 모든 단계가 맞으면 `MAC 데모 통과`를 출력합니다. 발표 중 단계마다 멈추려면 `--step`을 붙입니다.

```powershell
python tests/test_mac_demo.py
```

HTTP(S) 격리는 **에이전트 → 신뢰 상태 관리**에서 `agent-001`을 격리한 뒤 `python tests/test_agent_client.py tools/list`를 실행해 확인합니다. HTTP 403과 `agent quarantined`가 나오면 토큰을 새 값으로 교체하고 격리를 해제합니다. 같은 명령에 `--token <새 토큰>`을 붙이면 HTTP 200이 나옵니다. 이후 테스트에서 이 에이전트를 계속 사용하려면 새 토큰을 지정하세요.

### 6-6. 보호 폴더의 파일 접근 제어

#### 1. 테스트 폴더 만들고 MayAI 실행하기

1. 파일 탐색기에서 예를 들어 `C:\MayAI-test\protected` 폴더를 만듭니다. 메모장으로 그 안에 `notes.txt`와 `payroll.txt`를 만들고, 각각 `internal notes`와 `restricted payroll`을 적어 UTF-8로 저장합니다. 실제 급여 자료 대신 테스트 문구를 사용하세요.
2. Windows 시작 메뉴에서 **계정의 환경 변수 편집**을 검색해 엽니다. **사용자 변수**에 아래 값을 추가합니다. 이미 같은 이름의 변수가 있으면 기존 값을 기록해 두세요.

   | 변수 이름 | 테스트 값 예시 |
   |---|---|
   | `MAYAI_PROTECTED_DIR` | `C:\MayAI-test\protected` |
   | `NAC_DB_PATH` | `C:\MayAI-test\file-access-test.db` |
   | `MAYAI_ADMIN_KEY` | `file-test-admin-key` |

   `NAC_DB_PATH`에는 아직 파일이 없는 경로를 지정합니다. 이전 테스트에서 읽은 파일의 등급은 DB에 남아 다음 테스트 결과에 영향을 줄 수 있습니다.

3. 실행 중인 관리 서버를 종료합니다. 파일 탐색기에서 `MayAI-main` 폴더를 열고, 주소 표시줄에 `cmd`를 입력해 새 명령 프롬프트를 엽니다. `python MayAI.py`를 입력해 시작한 뒤 [MayAI 대시보드](http://127.0.0.1:8000/)를 엽니다. 대시보드가 관리자 키를 물으면 위에서 설정한 값을 입력합니다.

#### 2. 대시보드에서 에이전트와 파일 등록하기

1. **에이전트** 탭에서 아래 값으로 각각 등록합니다. 두 에이전트의 신뢰 상태는 **정상**이어야 합니다.

   | 에이전트 ID | 이름 | 토큰 | 출발지 IP | 허가 등급 |
   |---|---|---|---|---|
   | `file-a` | A | `test-token-a` | `127.0.0.1` | L2 |
   | `file-b` | B | `test-token-b` | `127.0.0.1` | L3 |

2. **파일 접근 제어** 탭에서 `notes.txt`는 **L2**, `payroll.txt`는 **L3**으로 등록합니다. 목록에 표시된 두 파일의 **파일 ID**를 기록합니다. 아래 요청 주소의 `{파일 ID}` 자리에 해당 숫자를 넣습니다.

#### 3. 읽기·수정·위임 테스트하기

파일 작업은 Postman 데스크톱 앱 같은 HTTP 요청 도구에서 실행합니다. 요청 방식은 모두 **POST**입니다. 주소에 `http://127.0.0.1:8000/api/file-access/{파일 ID}/`를 입력한 뒤, 표에 나온 `read`, `write`, `delegate` 중 하나를 붙입니다. 헤더와 본문을 채운 뒤 **Send**를 누릅니다.

- **Headers**에 `X-Agent-ID`와 `X-Agent-Token`을 추가합니다. 표에 나온 A 또는 B의 ID와 토큰을 입력합니다.
- 본문이 있는 요청은 **Body**에서 **raw**와 **JSON**을 선택해 표의 값을 붙여 넣습니다. 본문이 없는 요청에서는 **none**을 선택합니다.
- 2번에만 `X-MayAI-Delegation` 헤더를 추가합니다. 값은 1번 응답의 `delegation` 값입니다. 토큰은 5분 안에 한 번 사용할 수 있습니다.

| 순서 | 파일 | 에이전트 | 주소 끝 | 요청 본문 | 확인할 결과 |
|---|---|---|---|---|---|
| 1 | `notes.txt` | A | `delegate` | `{"executor_id":"file-b","operation":"read"}` | **200**. 응답의 `delegation` 값을 복사합니다. |
| 2 | `notes.txt` | B | `read` | 없음 | **200**. `content`에 `internal notes`가 표시됩니다. |
| 3 | `notes.txt` | B | `write` | `{"content":"updated notes"}` | **200**. 메모장으로 다시 열면 내용이 `updated notes`로 바뀝니다. |
| 4 | `payroll.txt` | A | `read` | 없음 | **403**과 `MAC_READ_UP_DENY`. A의 허가 등급보다 높은 파일입니다. |
| 5 | `payroll.txt` | A | `delegate` | `{"executor_id":"file-b","operation":"read"}` | **403**과 `MAC_READ_UP_DENY`. B에게 맡겨도 A의 허가 등급이 적용됩니다. |
| 6 | `payroll.txt` | B | `read` | 없음 | **200**. `restricted payroll`을 읽고 B의 보유 데이터 등급이 L3으로 올라갑니다. |
| 7 | `notes.txt` | B | `write` | `{"content":"blocked update"}` | **403**과 `MAC_WRITE_DOWN_DENY`. 메모장으로 다시 열면 `updated notes`가 그대로 있습니다. |

**감사 로그 → 파일 접근**에서 위임 발급, 파일 읽기, 수정, 차단 기록을 확인합니다. 테스트가 끝나면 관리 서버를 종료하고 추가한 사용자 변수를 제거하거나 기존 값으로 되돌립니다.

운영 환경에서는 OS 권한으로 에이전트의 직접 파일 접근을 막고, 파일 작업을 MayAI 파일 접근 API로 보냅니다. 보호 폴더 바로 아래에 있는 링크 없는 일반 파일과 최대 1 MiB의 UTF-8 텍스트를 지원합니다. 수정은 파일 전체 내용을 교체합니다.

## 7. ML 프롬프트 인젝션 탐지 (tools / resources / prompts)

선택 테스트입니다. [ML 배포 계획](tool-poisoning-ml-plan.md)에 따라 Prompt Guard 2 ONNX 모델과 `requirements-ml.txt`의 패키지를 준비합니다. **응답** 탭의 ML 상태와 실제 테스트 응답의 탐지 항목을 함께 확인합니다. ONNX 모델 파일이 없으면 선택 기능인 ML 탐지와 응답 화면의 ML 상태 카드가 꺼집니다. 규칙 기반 탐지와 응답 정책은 계속 적용됩니다. 아래 표의 ML 결과는 모델 로드와 추론이 가능한 환경에서 확인합니다.

### 7-1. 내용 인젝션

터미널 A를 `python tests/test_mcp_server.py --check-agent-headers`로 실행합니다.

| 명령 | 기대 finding |
|---|---|
| `python tests/test_agent_client.py tools/call fetch_page -a page=safe` | 없음 |
| `python tests/test_agent_client.py tools/call fetch_page -a page=evil` | `TOOL_RESULT_INJECTION` |
| `python tests/test_agent_client.py tools/call fetch_page -a page=evil_ko` | `TOOL_RESULT_INJECTION`, `ML_UNSUPPORTED_LANGUAGE` |
| `python tests/test_agent_client.py tools/call fetch_page -a page=quiet` | 간접 지시 예제. 현재 모델·규칙이 어떤 항목을 기록하는지 확인 |
| `python tests/test_agent_client.py resources/read file:///docs/readme.md` | 없음 (명령형 README, 오탐 확인용) |
| `python tests/test_agent_client.py resources/read file:///docs/notes.md` | `RESOURCE_CONTENT_INJECTION` |
| `python tests/test_agent_client.py resources/read file:///docs/notes_ko.md` | `RESOURCE_CONTENT_INJECTION`, `ML_UNSUPPORTED_LANGUAGE` |
| `python tests/test_agent_client.py resources/read file:///docs/logo.png` | `RESOURCE_BLOB_UNINSPECTED` |
| `python tests/test_agent_client.py prompts/get code_review -a "diff=+ print(1)"` | 없음 (지시문 템플릿, 오탐 확인용) |
| `python tests/test_agent_client.py prompts/get summarize -a topic=revenue` | `PROMPT_CONTENT_INJECTION` |

### 7-2. 정의 포이즈닝

터미널 A를 `python tests/test_mcp_server.py --check-agent-headers --poison`으로 재시작합니다.

| 명령 | 기대 finding |
|---|---|
| `python tests/test_agent_client.py tools/list` | `TOOL_DEFINITION_INJECTION` (+ 정의가 바뀌었으면 `TOOL_DEFINITION_CHANGED`) |
| `python tests/test_agent_client.py resources/list` | `RESOURCE_DEFINITION_INJECTION` |
| `python tests/test_agent_client.py prompts/list` | `PROMPT_DEFINITION_INJECTION` |

`resources/list`는 한국어 리소스(`회의록`)가 있어 `ML_UNSUPPORTED_LANGUAGE`가 함께 붙습니다.

### 7-3. 차단까지 확인

**응답 정책** 탭에서 `RESOURCE_CONTENT_INJECTION`에 대한 차단 정책을 추가합니다. **응답** 탭의 처리 모드를 **차단(ENFORCE)** 으로 바꾸고 `notes.md`를 다시 읽으면, 해당 항목이 탐지된 응답은 HTTP 403으로 차단됩니다.

### ML 끄기

기본 정책과 MAC을 먼저 확인할 때는 관리 API를 한 번 실행해 테스트 DB를 만든 뒤, 같은 `NAC_DB_PATH`를 쓰는 터미널에서 다음 명령으로 ML을 끌 수 있습니다. ML 테스트를 시작할 때는 `'0'`을 `'1'`로 바꿔 실행합니다.

```powershell
@'
import os
import sqlite3
from pathlib import Path

with sqlite3.connect(Path(os.environ["NAC_DB_PATH"]).resolve().as_uri() + "?mode=rw", uri=True) as conn:
    conn.execute("UPDATE settings SET value='0' WHERE setting_key='ml_enabled'")
'@ | python -
```

## 8. 정리 / 초기화

터미널 A·B·C와 실행 중인 STDIO 데모를 종료합니다. 다음 테스트에서는 새 DB 경로를 사용하거나, 위 준비 단계에서 지정한 테스트 DB 파일을 삭제합니다. 서버 등록, MAC 규칙, 세션, 감사 로그도 이 DB에 저장됩니다.

```powershell
Remove-Item -LiteralPath "$env:TEMP\nac-test.db"
```

## 체크리스트

- [ ] selftest OK
- [ ] 미등록 / 토큰 오류 / 정책 없음 → 403
- [ ] ALLOW 정책 → 200, 특정 도구 DENY → 403 (DENY 우선)
- [ ] URL의 포트 또는 경로가 달라지면 요청 정책으로 차단
- [ ] 같은 등록 MCP 서버의 HTTP·STDIO 트래픽 상세에 동일한 서버 ID 표시
- [ ] 요청·응답 본문 원문 조회에 관리자 키 적용
- [ ] 요청 민감정보 → 허용되지만 위험도·이벤트 기록
- [ ] 응답 DENY 정책: MONITOR는 기록만, ENFORCE는 JSON-RPC 403
- [ ] id 위조 / outputSchema / inputSchema / rug-pull 탐지
- [ ] MAC: 상위 등급 접근 차단, 하위 등급 유출 차단, 라벨 없음 = L4, 세션 초기화 후 다시 허용
- [ ] 관리자 키 없이 변경 요청 → 401, 조회는 그대로 가능
- [ ] 신뢰: 격리 시 HTTP(S)·STDIO 차단, 토큰 교체와 격리 해제 후 정상 복귀
- [ ] 감사 로그 해시 체인 정상 표시
- [ ] `--check-agent-headers`로 실행한 테스트 서버가 프록시를 통한 정상 요청에 HTTP 200 반환
