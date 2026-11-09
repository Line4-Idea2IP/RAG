# 원본 검토 및 최소 재활용 기록

- 검토일: 2026-11-09
- 저장소: https://github.com/Likelion14-CenterHackathon-F/RAG
- 기준 main 커밋: `c6ec3cffd9012017c81583a567b5540721f1ef41`
- GitHub 연결 도구로 실제 Python 내용을 읽었습니다. 전체 저장소/이력/데이터/환경파일은
  다운로드하지 않았습니다. 현재 작업 폴더는 비어 있었고 Git 저장소가 아니었습니다.

| 검토한 실제 파일 | 재활용 또는 배제 결정 |
|---|---|
| centerton_rag/retrieval.py | cosine distance→similarity, 컷오프, top-k, 주입 가능한 검색 패턴을 Idea2IP용으로 재작성. namespace/project/snapshot/index/model 필터 추가 |
| centerton_rag/answer.py | 근거 없음 게이트와 명시적 오류 원칙만 반영. 의료 프롬프트와 OpenAI Responses 호출은 배제 |
| centerton_rag/models.py | Pydantic API 경계 구조만 참고. 도메인 모델 전부 신규 정의 |
| centerton_rag/config.py | 환경변수 구성과 지연 의존성 원칙만 참고. 의료 색인/검색 allowlist/모델 설정 배제 |
| centerton_rag/main.py | FastAPI 경로 배선과 503 오류 노출 원칙 참고. 의료 API/게이트 배제 |
| scripts/serve_kure_embeddings.py | KURE-v1 /embed 요청·응답 계약 참고. 기존 서버 파일은 복사하지 않음 |
| scripts/ingest_rag_documents.py | 명시적 upsert, 본문 해시, 색인 판본 개념 참고. 의료 적재 스키마/원본 읽기/외부 비밀 로더 배제 |
| tests/test_retrieval_contract.py, tests/test_generation_gate.py | 경계값·부정 경로·주입 테스트의 구성 원칙 참고. 의료 fixture는 복사하지 않음 |
| pyproject.toml, centerton_rag/README.md | 기존 의존성과 실행 흐름 확인. 필요한 경량 의존성과 선택적 vector extra로 재구성 |

실행 모듈을 통째로 가져오면 의료 도메인과 외부 API 의존성이 섞이므로 필요한 범용 패턴만
새 모듈에 적응시켰습니다. 원본 의료 규칙·코퍼스·API 키·운영 접속정보는 포함하지 않았습니다.
GitHub 메타데이터상 원본 라이선스 표기는 없었습니다. 이 아카이브에서 원본 전체의
라이선스를 새로 선언하지 않습니다. 팀 외부 배포 시 원본 권리 관계는 별도로 확인하세요.

## 호환성 확인에 참고한 1차 문서

- llama.cpp server: https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md
- KURE-v1 model card: https://huggingface.co/nlpai-lab/KURE-v1
- pgvector SQL/cosine 연산: https://github.com/pgvector/pgvector

문서 확인은 사용자 Ubuntu에 설치된 실제 llama.cpp 빌드의 통합 검증을 대신하지 않습니다.
실제 법률 내용은 수집하거나 판단하지 않았고 공식 자료 판본 슬롯만 제공합니다.
