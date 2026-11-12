# MayAI 전시 부스 운영 가이드

| 번호 | 시연 | 입력하는 사람 | 보여줄 결과 |
|---|---|---|---|
| 1 | 악당 에이전트의 자료 반출 시도 | 관람객이 Claude Code 채팅에 입력 | 같은 가짜 고객 목록이 사내 보고 서버로는 전달되고, 외부 수집 서버로는 전달이 차단됨 |
| 2 | 파일 삭제 도구 정책 | 관람객이 입력하고 운영자가 정책을 전환 | 동일한 `delete_file` 호출이 정책에 따라 차단됐다가 허용됨 |
| 3 | 보호 파일 강제 접근제어(MAC) | 관람객이 Claude Code 채팅에서 역할과 파일을 선택 | L2 신입 요원은 내부 메모 읽기 허용·급여 파일 읽기 차단, L3 보안 책임자는 같은 급여 파일 읽기 허용 |

기본 관람 흐름은 **1 → 3**으로 약 3분을 잡는다. 도구 정책을 더 보고 싶어 하는 관람객에게 **2**를 추가한다. 나머지 기능은 설명으로 소개한다.

## 1. 장비 배치

- **MayAI PC와 모니터**에 대시보드를 띄운다. 시연 1·2는 **트래픽 피드**, 시연 3은 **감사 로그 → 파일 접근**을 연다.
- **노트북과 모니터**에 Claude Code 채팅을 띄운다. 노트북은 Python 3과 로그인한 로컬 Claude Code CLI가 필요하다.
- 두 장비를 서로 통신할 수 있는 같은 사설망에 연결한다. `ipconfig`로 실제 사용하는 인터페이스의 IPv4를 확인한다. 노트북에서 Claude 서비스를 이용할 인터넷 연결도 확인한다.

```text
노트북 Claude Code → 로컬 MCP bridge.py → MayAI PC 8080 → 사내 보고 서버 9100
                                       → MayAI PC 8081 → 외부 수집 서버 9101 (모의)
사내 보고 서버 9100 (파일 시연 도구) → 로컬 파일 접근 API 8000 → 보호 폴더 및 파일 접근 감사 로그
```

8080·8081은 고정된 테스트 서버로 연결하는 MayAI 리버스 프록시 포트다. 관리 API 8000과 테스트 서버 9100·9101은 MayAI PC의 루프백에 둔다. Windows 방화벽에서 수신 규칙이 필요하면 TCP 8080·8081을 노트북 IPv4에 한해 연다. 이 데모는 사설망에서 가짜 데이터와 행사 전용 토큰으로 진행한다.

## 2. MayAI PC 준비

모든 PC 명령은 `MayAI-main`에서 실행한다. `operate.ps1`은 PowerShell 7에서 실행한다. 기존에 구성된 Python 환경이 있으면 활성화한 뒤 `python`과 `mitmdump`를 사용한다.

```powershell
python -m pip install fastapi uvicorn mitmproxy
```

### 터미널 A · 관리 API와 보호 폴더

```powershell
$booth = Join-Path $env:TEMP 'mayai-booth-1112'
$env:MAYAI_PROTECTED_DIR = Join-Path $booth 'protected'
$env:NAC_DB_PATH = Join-Path $booth 'booth.db'
New-Item -ItemType Directory -Force $env:MAYAI_PROTECTED_DIR | Out-Null
Set-Content -Encoding utf8 (Join-Path $env:MAYAI_PROTECTED_DIR 'notes.txt') '데모 내부 업무 메모'
Set-Content -Encoding utf8 (Join-Path $env:MAYAI_PROTECTED_DIR 'payroll.txt') '데모 급여 자료 · 가상 직원 DEMO-001'
$env:MAYAI_ADMIN_KEY = '<행사 전용 관리자 키>'
python MayAI.py
```

처음 설정할 때는 아직 DB가 없는 폴더를 선택한다. `http://127.0.0.1:8000/`에서 대시보드를 열고 **관리자 키** 버튼에 설정한 키를 입력한다.

### 터미널 B·C · 수신 서버 두 개

터미널 B에는 기존 `booth-rookie`와 `booth-chief`를 등록할 때 사용한 파일 시연 토큰을 설정한다. 새 DB를 준비할 때는 터미널 E의 `MAYAI_BOOTH_FILE_TOKEN`과 동일한 값을 사용한다.

```powershell
# B · 사내 보고 서버 및 시연용 파일 읽기 도구
$env:MAYAI_BOOTH_FILE_TOKEN = '<PC 전용 파일 시연 토큰>'
python tests/test_mcp_server.py --port 9100 --check-agent-headers --booth-files
```

```powershell
# C · 외부 수집 서버 역할을 맡는 모의 서버
python tests/test_mcp_server.py --port 9101 --check-agent-headers
```

### 터미널 D · MayAI 리버스 프록시

`<MayAI PC IPv4>`를 노트북에서 접근할 PC의 IPv4로 바꾼다. `NAC_DB_PATH`는 터미널 A와 동일해야 한다.

```powershell
$env:NAC_DB_PATH = Join-Path $env:TEMP 'mayai-booth-1112\booth.db'
$pcIp = '<MayAI PC IPv4>'
mitmdump -s MayAI.py --listen-host $pcIp --set connection_strategy=lazy `
  --mode reverse:http://127.0.0.1:9100@8080 `
  --mode reverse:http://127.0.0.1:9101@8081
```

### 터미널 E · 시연 설정 및 운영

세 값은 행사 전용으로 정한다. 관리자 키는 터미널 A와 일치해야 한다. 노트북에는 `MAYAI_BOOTH_TOKEN`만 전달한다.

```powershell
$env:MAYAI_ADMIN_KEY = '<터미널 A와 같은 관리자 키>'
$env:MAYAI_BOOTH_TOKEN = '<노트북과 공유할 시연용 토큰>'
$env:MAYAI_BOOTH_FILE_TOKEN = '<PC 전용 파일 시연 토큰>'
./examples/booth/operate.ps1 -Action Configure -LaptopIp '<노트북 IPv4>'
```

`Configure`는 빈 행사 DB에 한 번 실행한다. 등록 중 실패했다면 오류를 해결한 뒤 A와 D를 같은 새 DB 경로로 다시 띄워 설정한다. 노트북 IP만 바뀌면 **에이전트 → 악당 에이전트 → IP 설정**에서 수정한다.

### 이미 구성한 전시 DB로 파일 읽기 체험 추가

1. 터미널 E에서 `MAYAI_ADMIN_KEY`를 설정하고 `./examples/booth/operate.ps1 -Action EnableFileTools`를 실행한다. 기존 전시 DB에 사내 보고 서버의 파일 읽기 MCP 도구 세 개를 호출할 수 있는 정책을 추가한다. 재실행해도 활성 정책이 중복 등록되지 않는다.
2. 터미널 B의 기존 사내 보고 서버를 종료하고, 위의 `--booth-files` 명령으로 다시 띄운다.
3. 노트북의 Claude Code를 종료하고 최신 `bridge.py`와 `CLAUDE.md`를 복사한 뒤 아래 노트북 준비 절차대로 Claude Code를 다시 시작한다.

## 3. 노트북 준비

1. `examples/booth` 폴더를 노트북으로 복사한다. 숨김 파일인 `.mcp.json`도 포함한다. 이 폴더에는 행사 파일만 둔다.
2. PowerShell 7에서 복사한 폴더로 이동한다. `python --version`, `claude --version`으로 실행을 확인한다. `python` 명령이 없으면 `.mcp.json`의 `command`를 노트북 Python 실행 파일의 절대 경로로 바꾼다.
3. 아래 명령을 실행한다. 도구 서버 승인 화면이 뜨면 `mayai-booth`를 확인하고 승인한다. `/mcp`에서 연결 상태를 확인한다. 같은 폴더의 [CLAUDE.md](../examples/booth/CLAUDE.md)가 시연 지침이다. [Claude Code MCP 설정](https://code.claude.com/docs/en/mcp) · [Claude Code CLI 옵션](https://code.claude.com/docs/en/cli-reference)

```powershell
$env:MAYAI_BOOTH_HOST = '<MayAI PC IPv4>'
$env:MAYAI_BOOTH_TOKEN = '<PC에서 등록한 노트북 시연 토큰>'
Test-NetConnection $env:MAYAI_BOOTH_HOST -Port 8080 -InformationLevel Quiet
Test-NetConnection $env:MAYAI_BOOTH_HOST -Port 8081 -InformationLevel Quiet
claude --strict-mcp-config --mcp-config .mcp.json --tools ""
```

`--tools ""`은 Claude Code 기본 도구를 끈다. 이 세션에서 MCP 호출 승인 화면이 뜨면 운영자가 행사 도구 이름을 확인하고 진행한다. 관람객은 채팅 입력을 사용한다.

## 4. 현장 진행

### 시연 1 · 자료 반출 시도

1. 관람객에게 “데모 고객 목록을 사내 보고 서버로 보내줘”를 입력하게 한다. `send_internal_report`가 가짜 목록을 보내고 결과에 `DEMO-001` 등이 표시된다.
2. “같은 데모 고객 목록을 외부 수집 서버로 보내줘”를 입력한다. `send_external_report` 호출이 `외부 수집 차단` 정책에 걸린다.
3. **트래픽 피드**에서 악당 에이전트의 두 **요청** 행을 보여준다. 상세를 열면 실제 목적지와 매칭 사유를 볼 수 있다. 수신 서버의 `echo`는 양쪽에서 동일한 도구이며, `bridge.py`가 같은 고정 목록을 각 목적지로 보낸다. 외부 수집 서버는 같은 PC에 띄운 모의 서버다.

### 시연 2 · 삭제 도구 정책 전환

1. **요청 정책**에서 `삭제 시연 차단`이 활성 상태인지 확인한다. “시연용 `booth-demo.txt` 삭제를 요청해줘”를 입력하면 **차단**된다.
2. `삭제 시연 차단`만 **비활성화**한다. 관람객이 같은 문장을 다시 입력하면 `삭제 시연 기본 허용`이 적용되고 `pretend-deleted booth-demo.txt`가 돌아온다. 테스트 도구는 모의 삭제 결과를 반환한다.
3. 두 요청의 판정을 보여준 뒤 `삭제 시연 차단`을 다시 **활성화**한다.

### 시연 3 · 같은 보호 파일, 다른 허가 등급

1. 대시보드에서 **파일 접근 제어**에 등록된 `notes.txt` L2와 `payroll.txt` L3를 보여준다. **감사 로그 → 파일 접근**으로 이동한다.
2. 관람객이 Claude Code에 아래 문장을 한 번씩 입력한다.

   | 입력 예시 | 결과 |
   |---|---|
   | “신입 요원으로 내부 메모를 읽어줘.” | **허용** · L2 메모 내용 표시 |
   | “신입 요원으로 급여 파일을 읽어줘.” | **차단** · `MAC_READ_UP_DENY` |
   | “보안 책임자로 같은 급여 파일을 읽어줘.” | **허용** · L3 급여 파일의 데모 내용 표시 |

3. 감사 로그에서 **신입 요원 · L2**와 **보안 책임자 · L3**의 기록을 비교한다. 트래픽 피드에는 `악당 에이전트`의 MCP 도구 호출 판정이, 파일 접근 감사 로그에는 선택한 역할의 실제 파일 접근 판정이 표시된다. MCP 도구 호출이 허용돼도 해당 역할의 파일 읽기는 MAC에서 차단될 수 있다.

## 5. 리허설과 대체 진행

- 개장 전에 노트북의 Claude Code로 시연 1의 두 요청을 실행한다. 채팅 결과와 함께 PC 트래픽 피드에 **사내 보고 서버 허용 → 외부 수집 서버 차단**이 찍혀야 한다.
- 시연 2의 두 판정과 차단 정책 재활성화를 확인한다. 시연 3도 Claude Code에서 세 문장을 실행하고 **허용 → 차단 → 허용**과 파일 접근 감사 기록 세 건을 확인한다.
- `invalid token`이면 두 장비의 시연용 토큰을 대조한다. 출발지 불일치라면 PC 트래픽 상세 또는 프록시 콘솔에서 실제 노트북 IP를 확인한다. 피드에 요청이 없다면 `/mcp` 상태와 포트 연결 결과를 확인한다.
- 파일 시연 도구가 트래픽 피드에서 차단되면 터미널 E에서 `EnableFileTools`를 실행했는지 확인한다. 호출은 허용됐지만 파일 시연 오류가 표시되면 터미널 B의 `--booth-files`와 파일 시연 토큰, 관리 API와 보호 파일 등록을 확인한다.
- Claude Code에 문제가 있으면 노트북에서 아래 명령으로 같은 MCP 어댑터와 MayAI 정책을 확인한다.

```powershell
@('send_internal_report', 'send_external_report', 'delete_file',
  'read_notes_as_rookie', 'read_payroll_as_rookie', 'read_payroll_as_chief') | ForEach-Object {
  @{ jsonrpc='2.0'; id=1; method='tools/call'; params=@{name=$_; arguments=@{}} } |
    ConvertTo-Json -Depth 4 -Compress
} | python bridge.py
```

노트북 경로를 사용할 수 없으면 MayAI PC의 터미널 E에서 `MAYAI_BOOTH_FILE_TOKEN`을 설정하고 `./examples/booth/operate.ps1 -Action Files`로 시연 3을 진행한다. 파일 접근 API의 **200 → 403 / `MAC_READ_UP_DENY` → 200**이 출력된다.

운영이 끝나면 노트북의 Claude 세션을 종료하고 PC의 프록시·테스트 서버·관리 API를 종료한다. 행사 때문에 열었던 방화벽 규칙이 있으면 제거한다.

## 6. 리허설 로그 정리

리허설이 끝나면 MayAI PC의 **관리 API(터미널 A)**와 **프록시(터미널 D)**를 `Ctrl+C`로 종료한다. 아래 명령을 `MayAI-main`에서 실행한다. `$boothDb`는 A와 D에서 실제 사용한 `NAC_DB_PATH`로 맞춘다. 기본 DB를 사용했다면 `(Resolve-Path .\nac.db).Path`를 지정한다.

```powershell
$boothDb = Join-Path $env:TEMP 'mayai-booth-1112\booth.db'
@'
import sqlite3
import sys
from contextlib import closing
from pathlib import Path

db = Path(sys.argv[1]).resolve(strict=True)
tables = ('response_bodies', 'request_bodies', 'ml_detections',
          'response_logs', 'logs', 'events')
print(db)
with closing(sqlite3.connect(db.as_uri() + '?mode=rw', uri=True)) as conn:
    conn.execute('PRAGMA foreign_keys = ON')
    with conn:
        conn.execute('BEGIN IMMEDIATE')
        for table in tables:
            deleted = conn.execute(f'DELETE FROM {table}').rowcount
            remaining = conn.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]
            print(f'{table}: deleted={deleted}, remaining={remaining}')
'@ | python - $boothDb
```

모든 `remaining`이 `0`이면 A와 D를 같은 DB 경로로 다시 띄우고 대시보드를 새로고침한다. 이 작업은 요청·응답 로그와 저장된 본문, 보안 이벤트, ML 탐지 기록을 정리한다. 에이전트, 정책, 파일 등급과 추가 전용 감사 로그는 보존된다.

시연 3의 **파일 접근 감사 로그까지 빈 상태로 시작**하려면 기존 DB를 보관하고 A와 D에 새 `NAC_DB_PATH`를 지정한 뒤 **터미널 E의 `Configure`**를 다시 실행한다. 새 DB에는 등록 과정에서 생긴 관리자 감사 기록이 남는다. **감사 로그 → 파일 접근** 필터는 첫 파일 읽기 전까지 비어 있다.
