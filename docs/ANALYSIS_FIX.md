# 실제 모델 분석의 필드 중복/누락 수정 (2026-11-10)

## 확인한 문제

실제 Ubuntu 호출에서 질문 생성은 성공했으나 분석과 Brief가
`MODEL_FIELD_MISMATCH: 분석 필드 중복/누락`으로 종료되었습니다.
이 오류는 모델 출력이 Pydantic의 5개 항목 배열 검증을 통과한 뒤,
target_field 집합이 필요한 5개 항목과 다를 때 발생합니다.
사용자 서버의 원시 응답이나 llama.cpp 빌드는 직접 확인하지 않았습니다.

기존 배열 스키마는 길이만 5개로 제한하며 각 target_field는 같은 enum을 사용합니다.
따라서 동일 target_field를 반복하고 다른 항목을 빠뜨린 응답도 JSON Schema를 만족합니다.
기존 테스트는 이런 응답을 차단하는지는 확인했으나, 모델에 보내는 스키마가 중복을
구조적으로 막는지는 검증하지 못했습니다.

## 변경

- 모델 전용 `NamedAnalysisDraft`에 5개의 필수 속성을 지정했습니다:
  work_overview, ai_usage, human_edit, selection_arrangement, creative_intent.
- 각 속성에는 disposition, source_ids, quotes만 있고 모델이 target_field를 선택하지 않습니다.
- 근거 없는 항목도 not_provided 및 빈 출처/인용으로 포함하도록 안내합니다.
- 서버가 고정 순서로 기존 공개 API의 fields 배열로 변환합니다. Spring 계약은 유지합니다.
- 출처 ID, 원문 전체 일치, 지정 필드의 진술 누락, 교차 필드 인용 검증은 유지합니다.
- 오류를 mock으로 대체하거나 누락된 분석을 임의로 채우지 않습니다.

## 검증

- 수정 전: 분석/Brief/기여 API의 고정 필수 속성 계약 테스트 3개 실패.
- 수정 후: 전체 `python -m pytest -q`에서 57 passed.
- 실제 채팅 클라이언트와 주입한 HTTP 응답으로 3개 API의 성공 경로 및
  누락 속성/추가 속성/이전 중복 배열의 차단을 검증했습니다.
- 실제 Ubuntu Qwen3-VL 응답으로는 패치 적용 후 재검증해야 합니다.
- 기존 Starlette TestClient의 httpx deprecation warning 1개는 남아 있습니다.

## Ubuntu 적용

기준 커밋은 e5a6267475d7a615cd9e0a0305a4a1db0a7cd3a2입니다.
패치 파일을 Ubuntu의 ~/Downloads/idea2ip-analysis-fix.patch에 저장한 경우:

```bash
cd ~/idea2ip-rag
git status --short
git apply --check ~/Downloads/idea2ip-analysis-fix.patch
git apply ~/Downloads/idea2ip-analysis-fix.patch
source .venv/bin/activate
python -m pytest -q
```

적용 검사가 실패하면 실제 코드와 기준 파일이 다른 것이므로 강제로 적용하지 마세요.
기존 FastAPI 터미널에서 Ctrl+C로 종료한 뒤 다음 명령으로 다시 실행합니다.
llama.cpp는 계속 실행해 두며 .env 변경이나 DB 추가는 필요하지 않습니다.

```bash
cd ~/idea2ip-rag
source .venv/bin/activate
python -m uvicorn idea2ip.main:app --host 127.0.0.1 --port 8000
```

새 터미널에서 이전과 같은 samples/project.json으로 /answers/analyze와 /brief를 호출하세요.
한글을 이스케이프 없이 보려면 `python3 -m json.tool --no-ensure-ascii`로 출력합니다.
