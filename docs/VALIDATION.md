# 검증 기록

검증일: 2026-11-09 (한국 시간). Windows / Python 3.13.5.
실행 패키지의 구체적인 버전은 `constraints-tested.txt`에 기록했습니다.
아래 명령의 python은 작업용 가상환경의 Python입니다.

| 검증 | 실행 명령 | 실제 결과 |
|---|---|---|
| API/근거/모델 실패/검색/판본 회귀 | `python -m pytest -q` | 52 passed |
| 정적 검사 | `python -m ruff check .` | All checks passed |
| 포맷 검사 | `python -m ruff format --check .` | 통과 |
| 독립 샘플 흐름 | `python -m scripts.demo` | 질문→분석→기여 구조→Brief 호출 성공 |
| 실제 HTTP | `python -m scripts.http_smoke` | 임시 uvicorn의 health=200, brief=200, sections=5, mode=mock |
| API 명세 생성 | `python -m scripts.export_openapi` | docs/openapi.json 생성 |
| wheel 패키징 | `python -m build --wheel --no-isolation` | idea2ip_ai-0.1.0-py3-none-any.whl 빌드 성공 |

Windows 실행 제한 안에서는 asyncio의 내부 로컬 소켓 생성이 멈췄습니다. 스택을 확인한 뒤
로컬 소켓 사용이 가능한 실행 환경에서 동일 API 테스트와 HTTP smoke를 실행해 통과했습니다.
프로젝트 코드를 바꾸거나 검사를 생략해 우회하지 않았습니다. pytest는 기존 Anaconda의
무관한 플러그인 영향을 배제하기 위해 `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`로 실행했습니다.

Starlette 1.10.0의 TestClient가 httpx 대신 httpx2 사용을 권고하는 deprecation warning이
1개 있었습니다. 현재 고정된 검증 버전에서는 52개 테스트가 모두 통과했으며 경고를 숨기지
않았습니다. 런타임의 llama.cpp 호출은 httpx를 직접 사용합니다.

## 검증 범위의 한계

- 사용자의 Ubuntu llama.cpp/Qwen3-VL 서버에 실제 접속하지 않았습니다. 채팅 payload,
  JSON Schema, 이미지 content 형식과 오류 응답은 주입한 HTTP 응답으로 검증했습니다.
- 실제 KURE 모델 다운로드/임베딩, 실제 PostgreSQL/pgvector 서비스의 적재·검색은
  실행하지 않았습니다. SQL 바인딩의 project/snapshot/index 경계, cosine 임계값,
  임베딩 실패, 교차 프로젝트 자료 차단을 테스트했습니다.
- 공식 법령/신청 지침은 미검토 자리표시자입니다. 법률 내용을 검증하거나 현재 법적 효력을
  판정하지 않았습니다. 가상의 테스트 판본으로 해시·호스트·날짜·검토 상태만 검증했습니다.
- Spring 예시 코드는 실제 Spring 프로젝트에서 컴파일하지 않았습니다. JSON 계약과
  OpenAPI를 기반으로 연동할 수 있도록 준비했습니다.
- 동시 부하, 실제 이미지 관찰 정확도, 인터뷰 품질에 대한 실제 모델 평가는 별도 작업입니다.

압축 시 `.env`, 가상환경, 캐시, 원본 저장소, build/dist를 제외합니다. ZIP CRC와 각 파일의
SHA-256은 `scripts.package`에서 검사하며 파일 목록은 `docs/FILE_MANIFEST.json`에 남깁니다.
