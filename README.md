# Idea2IP AI · RAG Starter

Spring Boot DB 없이 프로젝트 스냅샷 JSON으로 실행하는 FastAPI 서비스입니다.
기본값은 **mock + 검색 비활성화**이며 외부 모델, OpenAI 키, vector DB가 필요 없습니다.
실제 생성은 기존 Ubuntu의 Qwen3-VL-8B-Instruct / llama.cpp에 연결합니다.
PDF 생성·파일 영구 저장·로그인·프로젝트 권한 확인은 Spring Boot의 책임입니다.

## 빠른 시작

Python 3.11 이상에서 압축을 풀고 **이 README가 있는 폴더**에서 실행하세요.

```bash
python -m venv .venv
# Ubuntu/macOS
source .venv/bin/activate
# Windows PowerShell에서는 대신: .\.venv\Scripts\Activate.ps1
python -m pip install -e ".[test]"
# Ubuntu: cp .env.example .env
# PowerShell: Copy-Item .env.example .env
python -m scripts.demo
python -m pytest -q
python -m uvicorn idea2ip.main:app --host 127.0.0.1 --port 8000
```

설치 결과를 재현하려면 `pip install -c constraints-tested.txt -e ".[test]"`를 사용하세요.
`constraints-tested.txt`는 검증 환경의 핵심 패키지 버전이며 모든 플랫폼을 위한 전체 잠금 파일은 아닙니다.
`http://127.0.0.1:8000/docs`에서 요청 형식과 응답 스키마를 확인할 수 있습니다.
`scripts.demo`는 서버를 띄우지 않고 네 개의 API를 호출하여 `build/demo-output.json`을 만듭니다.
실제 HTTP 호출 예시:

```bash
curl -X POST http://127.0.0.1:8000/v1/projects/project-moon-garden/brief \
  -H 'Content-Type: application/json' --data-binary @samples/project.json
```

PowerShell에서는 `curl.exe`를 사용하거나 다음과 같이 호출하세요.

```powershell
Invoke-RestMethod -Method Post -Uri 'http://127.0.0.1:8000/v1/projects/project-moon-garden/brief' -ContentType 'application/json; charset=utf-8' -Body (Get-Content samples/project.json -Raw -Encoding UTF8)
```

## 실제 Qwen3-VL 연결

`.env`에서 다음 두 항목을 바꾸고 FastAPI를 다시 시작합니다.

```dotenv
IDEA2IP_MODE=live
IDEA2IP_LLM_BASE_URL=http://localhost:8081/v1
IDEA2IP_LLM_MODEL=idea2ip-vl
```

기존 llama.cpp 실행 환경을 재설치하거나 모델 파일을 복사하지 않습니다.
서버 별칭은 `--alias idea2ip-vl`, 포트는 `8081`이어야 합니다. 이미지 처리는 해당 모델에
맞는 `--mmproj` 및 멀티모달 지원 빌드가 필요합니다. 사용 중인 llama.cpp 빌드 버전은
아직 확인되지 않았으므로 `/v1/models`와 실제 텍스트/이미지 요청으로 호환성을 확인하세요.
채팅 요청은 `/v1/chat/completions`, 구조화 응답은
`response_format.json_schema.schema`를 사용합니다. 응답을 Pydantic으로 다시 검증합니다.
스키마가 무시되는 구버전이나 응답 잘림은 `MODEL_INVALID_OUTPUT` 오류로 반환합니다.
모델 호출에 OpenAI SDK나 OpenAI API 키는 사용하지 않습니다.

FastAPI와 모델이 **같은 Ubuntu 환경**에서 실행될 때 localhost 설정을 그대로 사용합니다.
Windows, WSL, Docker가 서로 다른 환경이라면 localhost가 다른 컴퓨터/네트워크를 뜻할 수 있으므로
FastAPI에서 접근 가능한 모델 주소로 설정해야 합니다. 기본 API 바인딩은 127.0.0.1입니다.

실제 연결 오류를 mock으로 자동 대체하지 않습니다. 모델 연결 불가 503, 시간 초과 504,
잘못된 모델 출력/출처 검증 실패 502를 반환합니다. 단, 근거가 전혀 없는 요청은
모델을 호출하지 않고 고정 확인 질문과 미확인 상태를 반환합니다.

## 인터뷰와 근거 원칙

1. Spring은 권한을 확인한 현재 프로젝트 스냅샷을 전달합니다.
2. 검색을 켰다면 같은 프로젝트·스냅샷·색인 버전의 근거만 추가합니다.
3. `target_field`별 질문을 생성하고 사용자 진술의 답변 상태를 분석합니다.
4. 사용자 진술을 원문 그대로 인용해 창작 기여 관련 항목으로 분류합니다.
5. 고정된 5개 섹션과 출처 목록으로 Copyright Brief 초안을 조립합니다.

| 근거 타입 | 의미와 제한 |
|---|---|
| `USER_STATEMENT` | 사용자 진술. 사실 인증이나 저작권 인정이 아님 |
| `ATTACHED_FILE` | 문서 추출문/첨부 메타데이터. 파일만으로 창작 주체를 인정하지 않음 |
| `IMAGE_OBSERVATION` | 모델이 관찰한 시각적 특징. 같은 프로젝트 첨부 부모 ID 필요 |
| `OFFICIAL_GUIDE` | 서버의 검토된 공식 판본만 허용. 사용자 창작 사실의 근거로 전환하지 않음 |
| `UNVERIFIED` | 확인되지 않은 메모. 사실 분석에 사용하지 않음 |

분석 대상 필드는 `work_overview`, `ai_usage`, `human_edit`, `selection_arrangement`,
`creative_intent`입니다. 상태는 `MISSING`, `UNCLEAR`, `USER_REPORTED`, `CONFLICTED`입니다.
`USER_REPORTED`는 해당 질문에 대한 진술이 있다는 의미이며 독립 검증이나 창작성 판정이 아닙니다.
직접 작업이 **없다**는 답변도 그대로 기록하며, 존재하는 창작 기여로 바꿔 쓰지 않습니다.
Contribution의 `statement`는 긍정/부정을 포함한 사용자 원문이며 기여도 점수를 의미하지 않습니다.

mock은 의미·부정·상충을 분석하지 않으므로 진술이 있으면 `UNCLEAR`, 없으면 `MISSING`을
반환합니다. 따라서 mock 샘플의 `contributions`는 비어 있으며 보완 질문을 남깁니다.
live 분석과 창작 기여 분류의 정상 흐름은 테스트의 검증된 모델 응답으로도 확인합니다.

출처 ID, 프로젝트 범위, 부모 첨부, 인용문 전체 일치, 지정된 필드의 진술 누락을
서버에서 검사합니다. 짧은 부분 인용으로 부정 표현이 사라지지 않도록 `quotes`는
원문 `content` 전체와 일치해야 합니다. Brief 본문도 이 원문과 고정 문구로 구성합니다.
다만 질문의 의미 적절성·모델의 상충 판정·이미지 관찰 정확성까지 기계적으로 증명하는 것은
아니므로 실제 모델 평가와 최종 사용자 확인이 필요합니다.

이미지 API는 최대 5MB의 PNG/JPEG base64 data URI만 받습니다. 외부 URL과 로컬 파일 경로는
받지 않습니다. mock은 이미지 특징을 만들어내지 않습니다. live의 관찰 결과는 Spring이
`IMAGE_OBSERVATION`으로 저장한 뒤 `parent_source_ids`와 함께 다음 스냅샷에 포함합니다.
실제 원본 이미지·추출 텍스트·출처의 진위와 소유권은 Spring에서 관리합니다.
문서/PDF 추출기와 OCR, PDF 리포트 렌더러는 이 초기 서비스의 범위에 포함하지 않습니다.

## 선택적 KURE-v1 / pgvector

현재 Spring DB가 없어도 됩니다. 검색을 사용할 때만 별도의 Idea2IP DB를 준비하세요.

```bash
python -m pip install -e ".[vector]"
# DB 관리자 권한으로 별도 DB에 한 번 적용
psql "$IDEA2IP_DATABASE_URL" -f sql/001_vector.sql
python -m scripts.ingest --project samples/project.json
python -m scripts.ingest --legal
```

접속 문자열은 환경변수 또는 `.env`의 `IDEA2IP_DATABASE_URL`로 설정하며 실제 비밀을
터미널 기록이나 Git에 넣지 마세요. `psql`은 `.env`를 자동으로 읽지 않으므로 위 명령의
변수는 셸에 따로 설정되어 있어야 합니다. API와 적재 스크립트는 `.env`를 읽습니다.

| `IDEA2IP_RETRIEVAL` | 동작 |
|---|---|
| `none` | 기본. 요청 스냅샷만 사용, 법률 검색 안 함 |
| `fixture` | 요청 자료/검토된 법률 카탈로그에 단어 매칭. 의미 검색 아님 |
| `pgvector` | KURE-v1 1024차원 cosine 검색, 임계값 및 top-k 적용 |

기본 KURE 구현은 `sentence-transformers`를 지연 로딩합니다. 최초 실행 시 모델 다운로드와
메모리 자원이 필요합니다. Qwen 채팅 모델을 임베딩으로 쓰지 않습니다.
기존 KURE `/embed` 서비스를 사용할 경우 `IDEA2IP_EMBEDDING_URL=http://localhost:8001/embed`로
설정할 수 있습니다. 요청은 `{model,input:[text]}`, 응답은
`{model,dimensions:1024,embeddings:[[...]]}`이며 실제 모델명과 차원을 검사합니다.
외부 임베딩 서비스를 쓰면 API 환경에는 psycopg만 필요하고 sentence-transformers는
그 서비스에 설치하면 됩니다.

`index_version`, `snapshot_version`, 프로젝트 ID, 임베딩 모델을 SQL에서 모두 제한합니다.
`source_id`별 자료는 하나의 소규모 청크로 취급하며 큰 문서는 Spring/적재 전처리에서
페이지·절 단위로 나눠 ID와 `locator`를 부여하세요. 현재 content 최대 8000자, 요청 총량
100000자입니다. 모델 컨텍스트 한도에 맞는 더 작은 스냅샷을 권장하며 자동 절삭하지 않습니다.

적재는 트랜잭션 단위 upsert입니다. 기존 스냅샷에서 자료를 삭제하거나 수정할 때는
새 `snapshot_version`으로 전량 적재하고 요청도 새 버전을 사용하세요. 삭제된 자료가
남은 기존 스냅샷 ID를 재사용하지 마세요. 색인 알고리즘/모델 변경은 새 `index_version`으로
적재합니다. 이전 버전은 남겨 두어 Spring의 설정을 되돌릴 수 있습니다. 적재 API는 공개하지
않으며 법률 카탈로그 변경·색인 작업은 운영자 관리 작업입니다.

실제 PostgreSQL/KURE 서비스에서의 통합 실행은 전달 환경에서 별도로 확인해야 합니다.
기본 테스트는 주입한 검색 결과와 연결 실패를 검사하며 실제 DB 연결 성공을 주장하지 않습니다.

## 공식 법률자료 판본

`samples/legal_catalog.json`은 **실제 법률 내용이 없는 자리표시자**입니다.
`reviewed=false`, 날짜 미지정, 해시 불일치이므로 검색과 리포트 근거에서 제외됩니다.
실제 적용 시 공식 원문 URL, 발행기관, 판본명, 발행/시행/수집 날짜, 본문 SHA-256,
검토 완료 여부를 입력하세요. 시행 종료일이 있으면 `effective_to`를 지정합니다.
공식 호스트 허용 목록, 시행 기간, 미래 날짜, 본문 해시를 검사하며 자동으로
사이트에서 법률을 내려받거나 최신 법률이라고 판정하지 않습니다.
호스트 목록은 `idea2ip/legal.py`에 있습니다. 새로운 공식 기관 추가도 검토 후 수행하세요.

판본마다 새로운 source ID를 사용하고 이전 판본을 덮어쓰지 마세요. legal 검색 결과는
현재 서버 카탈로그와 내용까지 정확히 일치해야 채택합니다. 잘못된 적재·만료·미검토 자료는
제외됩니다. 자료가 없으면 필요한 신청 서류를 임의로 나열하지 않고 미연결 상태를 남깁니다.
기준 날짜는 서버의 실행 날짜이며 과거 사건의 법률 판단 기능은 제공하지 않습니다.

## Spring Boot 연동

상세 계약: [docs/API_CONTRACT.md](docs/API_CONTRACT.md), 기계 판독 명세:
[docs/openapi.json](docs/openapi.json). `/openapi.json`에서도 동일 명세를 받을 수 있습니다.
프로젝트 권한을 확인한 내부 요청만 전달하고 `.env`에 `IDEA2IP_SERVICE_TOKEN`을 설정한 뒤
`X-Service-Token` 헤더로 인증하세요. 토큰이 비어 있으면 로컬 개발용으로 인증이 생략됩니다.
이 공유 토큰은 프로젝트별 사용자 권한을 확인하지 않습니다. 외부 공개 전에 Spring의
사용자 권한 검증, 내부 네트워크 제한 및 게이트웨이 요청 용량 제한을 구성해야 합니다.

Python은 상태를 저장하지 않습니다. 답변, 첨부 원본, 인터뷰 이력, Brief/PDF 버전 저장은
Spring이 담당합니다. 재시도 시 모델 문구가 달라질 수 있으므로 Spring에서 작업 ID별
완료 결과를 저장하고, 동일 `snapshot_version`에 대한 중복 결과를 정책에 따라 처리하세요.

## 구조와 검증

```text
idea2ip/       설정, Pydantic 모델, 채팅 클라이언트, 근거 엔진, 법률 판본, 검색, API
samples/       독립 실행용 프로젝트 JSON, 미검토 법률 자리표시자, mock 결과 예시
scripts/       demo, OpenAPI 내보내기, 명시적 vector 적재
sql/           별도 vector DB 스키마
tests/         API, 근거 검증, 채팅 계약/오류, 검색 격리, 판본 검증
docs/          API 계약, OpenAPI, 원본 검토/재활용 기록, 검증 기록
```

```bash
python -m pytest -q
python -m ruff check .
python -m ruff format --check .
python -m scripts.demo
python -m scripts.export_openapi
python -m scripts.http_smoke
python -m build --wheel --no-isolation
```

원본 실제 소스 검토와 재활용 내역은 [docs/PROVENANCE.md](docs/PROVENANCE.md)에 있습니다.
의료 분류·프롬프트·데이터셋·기존 `.env`·API 키는 포함하지 않았습니다.
