# MayAI

AI 에이전트와 MCP 서버 사이의 요청·응답을 정책으로 제어하는 보안 게이트웨이입니다. 첫 화면의 **보안 브리핑**에서 최근 24시간 트래픽, 미처리 이벤트, 에이전트 상태와 정책을 볼 수 있습니다.

- **HTTP(S)** 요청과 응답을 검사하고 정책에 따라 허용하거나 차단합니다.
- **파일 접근 제어**는 보호 폴더에 등록한 텍스트 파일에 등급을 지정하고, MayAI API를 통한 읽기·수정·위임을 검사합니다.
- **에이전트 격리**는 HTTP(S)와 STDIO에 공통 적용됩니다. 파일 접근 API도 격리된 에이전트를 차단합니다.
- **STDIO**의 MCP 도구·리소스·프롬프트 접근 제어는 관리 API에서 설정할 수 있습니다.

## Windows에서 시작하기

이 배포본은 Python 3.14 환경에서 확인했습니다. 압축을 푼 뒤 `MayAI-main` 폴더에서 명령 프롬프트를 엽니다.

```cmd
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe MayAI.py --selftest
.venv\Scripts\python.exe MayAI.py
```

브라우저에서 [MayAI 대시보드](http://127.0.0.1:8000/)를 엽니다. 기존 DB 없이 시작하면 `nac.db`가 생성됩니다. 관리자 키를 환경 변수 `MAYAI_ADMIN_KEY`로 지정하거나, 첫 실행 때 콘솔에 표시되는 키를 저장해 두세요. 다른 테스트 DB를 쓰려면 `NAC_DB_PATH`를 설정합니다.

대시보드 실행 후 [테스트 가이드](docs/TESTING_GUIDE.ko.md)의 **2~4장** 순서대로 테스트 MCP 서버와 프록시를 띄우고, 에이전트와 정책을 등록하면 요청·응답 시연을 진행할 수 있습니다. 파일 시연은 **6-6절**을 참고하세요.

## 포함 파일

| 항목 | 용도 |
|---|---|
| `MayAI.py`, `dashboard.html` | 관리 서버, 보안 프록시, 대시보드 |
| `requirements.txt` | 실행 및 자체 테스트에 쓰는 패키지 |
| `tests/` | 테스트 MCP 서버, 에이전트 클라이언트, STDIO MAC 데모 |
| `docs/TESTING_GUIDE.ko.md` | 설정과 기능별 테스트 |
| `examples/` | MCP 클라이언트 및 ML 매니페스트 설정 예시 |
| `requirements-ml.txt`, `models/prompt-injection/` | 선택 기능인 ML 탐지에 쓰는 패키지와 모델 설정 |

기존 DB, 관리자 키, 보호 파일, 가상환경은 배포본에 포함하지 않습니다. 선택 기능인 ML 탐지의 ONNX 가중치는 별도로 준비해야 합니다. 요청 정책과 규칙 기반 응답 탐지·차단 시연은 ONNX 없이 진행할 수 있습니다.
