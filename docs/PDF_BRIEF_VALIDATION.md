# Brief 인용 복원 검증 (2026-11-12)

시작 기준: `main`, `66f43c4`. 적용할 AGENTS.md는 없었다.
기존 이미지 질문 개선 변경(docs/QUESTION_QUALITY.md, engine.py, models.py,
test_image_questions.py)은 보존하고 이번 커밋에서는 해당 기존 변경을 제외한다.
공통 파일은 이번 작업의 분석 스키마/검증 및 모델 응답 fixture 변경만 스테이징한다.

## 확인한 원인과 수정

Spring의 `build/e2e-pdf/RESULTS.md` 및 실패 JSON에 502 INVALID_QUOTE가 기록돼 있었다.
최초 긴 요청 JSON 자체는 덮어써졌으나 `run_e2e.py`의 최초 sample 리터럴에 긴 입력이 남아 있어
그 입력으로 실제 모델을 다시 호출했다. 동일한 INVALID_QUOTE를 재현했다.
모델의 5개 quotes는 해당 필드에 해당하는 부분 문장이었고, 서버는 전체 content 일치를
요구했다. 이번 재현의 원인은 부분 인용과 전체 원문 검증 계약의 불일치였다.
과거 실행의 원시 모델 응답은 남아 있지 않아 당시 생성 문자열까지 동일했다고 주장하지 않는다.

이제 내부 NamedAnalysisDraft의 각 필드는 disposition, source_ids만 받는다.
FastAPI는 ID의 존재/중복/스냅샷 범위, 사용자 진술 여부, 대상 필드, 지정 진술 누락,
상충 상태의 최소 진술 개수를 검사한 뒤 원본 content를 quotes에 채운다.
공개 응답의 quotes 및 Brief 구조는 유지한다. 상충 진술은 버리지 않는다.

## 검증 결과

- 동일한 긴 입력으로 수정 후 실제 모델 Brief: live, DRAFT, 5개 섹션 성공.
  별도 분석 호출에서도 반환된 quotes가 원문 전체와 같은지 확인했다.
- 기존 미커밋 변경을 포함한 작업 트리 전체 `pytest -q`: 110 passed.
  Starlette/httpx 지원 중단 경고 1건. Ruff check와 format --check 통과.
  스테이징된 파일만 별도 디렉터리로 추출한 독립 검사도 103 passed 및 Ruff 두 검사 통과.
- 없는/중복 ID, 타 필드 진술, 첨부 자료/이미지 관찰 인용, 지정 필드 근거 누락 차단 회귀 유지.
  긴 원문/공백/줄바꿈 복원, 상충 진술 보존/최소 개수 및 모델 quotes 속성 차단 검사 추가.
- 공식 판본의 HTTPS 호스트, 날짜, reviewed, 본문 해시 및 카탈로그 일치 검증 유지.
  명백한 가상 테스트 판본으로 검색 채택 및 Brief의 판본 정보 보존 검사 추가.
  기본 카탈로그 자리표시자의 reviewed=false는 그대로다. 실제 검토된 공식 자료는 없다.
- Spring API의 새 PDF 버전 검증에는 실제 모델과 PostgreSQL을 사용했다.
  상세 내용은 BE 저장소의 `docs/PDF_RAG_VALIDATION.md`에 있다.

재현 입력/모델 원문/수정 후 결과는 Git 제외 `build/pdf-revision/`에 보관했다.
실제 공식 자료 연결, pgvector 및 새 이미지 관찰은 이번 검증 범위 밖이다.
