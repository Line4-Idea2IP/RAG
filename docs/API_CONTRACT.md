# Spring Boot ↔ Idea2IP AI API v1

HTTP/JSON UTF-8, 필드 이름 snake_case. 모든 POST의 경로 project_id는 본문 context의
project_id와 일치해야 합니다. 본문에 다른 프로젝트 자료나 중복 source_id가 있으면 422입니다.
`X-Service-Token`은 서버 설정 시 필수입니다. 프로젝트별 접근 권한은 Spring에서 검증합니다.

| API | 요청 본문 | 주요 응답 |
|---|---|---|
| `GET /health/live` | 없음 | 프로세스 생존, mode, retrieval, dependencies_checked=false |
| `POST /v1/projects/{project_id}/questions` | `{context,target_field}` | question, target_field, source_ids, mode |
| `POST /v1/projects/{project_id}/answers/analyze` | ProjectContext | 5개 fields, status, 원문 quotes, source_ids |
| `POST /v1/projects/{project_id}/contributions` | ProjectContext | 사용자 진술의 category, statement, source_ids, unresolved_fields |
| `POST /v1/projects/{project_id}/brief` | ProjectContext | 5개 sections, sources, legal_editions, notices |
| `POST /v1/projects/{project_id}/images/observe` | `{context,attachment_source_id,image_data_uri}` | observations, limitations, parent_source_ids |
| `POST /v1/projects/{project_id}/retrieval/search` | `{context,query,scope}` | backend, scope, hits[source,similarity] |

ProjectContext의 필수 항목: project_id, title. snapshot_version 기본값은 sample-v1이지만
Spring 연동에서는 반드시 명시하세요. sources는 최대 100개이며 Source의 필수 항목은
source_id, project_id, kind, title, content입니다. target_field, parent_source_ids, locator는
선택 항목입니다. `IMAGE_OBSERVATION`의 부모는 같은 context에 포함된 ATTACHED_FILE이어야 합니다.
OFFICIAL_GUIDE는 클라이언트가 제출할 수 없습니다.

분석 요청의 인터뷰 답변은 USER_STATEMENT로 넣고 원래 질문의 target_field를 지정합니다.
각 진술을 짧고 응집력 있게 저장하세요. live 모델이 지정 필드의 진술을 하나라도 누락하면
오류를 반환합니다. 출처 ID는 실제 자료를 식별하는 안정적인 ID이며 파일 저장 URL이 아닙니다.
스냅샷 제목은 메타데이터이고 작품 사실은 반드시 sources에 명시해야 합니다.

질문 요청 예시:

```json
{
  "context": {
    "project_id": "project-001",
    "title": "달빛 정원",
    "snapshot_version": "v1",
    "sources": []
  },
  "target_field": "human_edit"
}
```

간단한 Spring RestClient 호출 예시 (Spring 프로젝트 파일을 생성/수정하지 않음):

```java
JsonNode brief = RestClient.builder()
    .baseUrl(aiBaseUrl)
    .defaultHeader("X-Service-Token", serviceToken)
    .build()
    .post()
    .uri("/v1/projects/{projectId}/brief", projectId)
    .contentType(MediaType.APPLICATION_JSON)
    .body(projectSnapshot)
    .retrieve()
    .body(JsonNode.class);
```

projectSnapshot은 sources를 포함한 ProjectContext DTO입니다. 이 예시는 해당 Java 환경에서
컴파일하지 않았습니다. 연결/읽기 timeout은 사용 중인 Spring HTTP 클라이언트에 별도로 설정하세요.
Brief는 순차적으로 분석·법률 검색을 실행하므로 Python의 모델 timeout(기본 90초),
임베딩 로딩/timeout, DB timeout을 포함한 전체 호출 예산을 정해야 합니다.
핵심 프로세스의 health는 외부 모델·DB 준비 상태를 보장하지 않습니다.

Brief의 `sections`는 다음 **5개 키**만 갖습니다.

1. work_overview — 작품 개요에 관한 진술
2. ai_usage — AI 활용 내역에 관한 진술
3. human_contribution — 직접 수정·선택 배치·창작 의도에 관한 진술
4. evidence_summary — 근거 타입과 자료 목록
5. gaps_and_guidance — 보완 질문과 검토된 공식 지침

각 섹션은 title, status, statements, source_ids를 갖습니다. 최상위 status는 항상 DRAFT입니다.
각 section.source_ids는 최상위 sources에 존재합니다. 법률자료가 있으면 legal_editions에
판본 메타데이터도 보존합니다. Spring은 응답 mode, snapshot_version, schema_version,
전체 sources/판본을 Brief 버전과 함께 저장하고 사용자 확인 뒤 PDF 생성에 사용하세요.

| 상태 코드 | error.code 예 | Spring 처리 |
|---|---|---|
| 401 | UNAUTHORIZED | 내부 인증 설정 확인, 자동 재시도 안 함 |
| 422 | INVALID_REQUEST, PROJECT_MISMATCH, SOURCE_CONFLICT | 스냅샷/입력/색인 수정 |
| 502 | MODEL_INVALID_OUTPUT, INVALID_QUOTE, INVALID_SOURCE_REFERENCE, MODEL_EVIDENCE_OMITTED | 결과 저장/확정하지 말고 확인 필요로 처리 |
| 503 | MODEL_UNAVAILABLE, MODEL_HTTP_ERROR, EMBEDDING_UNAVAILABLE, VECTOR_DB_UNCONFIGURED, VECTOR_DB_UNAVAILABLE, SCOPE_VIOLATION | 일시 장애 구분 후 제한적 재시도, mock으로 자동 대체 금지 |
| 504 | MODEL_TIMEOUT | 작업을 미완료로 표시, 사용자 재시도 허용 |

오류 형태: `{"error":{"code":"MODEL_UNAVAILABLE","message":"llama.cpp 연결 불가"}}`.
전체 오류 코드와 스키마의 최종 근거는 코드와 OpenAPI입니다. 모델 응답 본문·DSN·업로드
내용은 오류에 포함하지 않습니다. 이 서비스는 영구 저장/결과 캐시/작업 큐를 제공하지 않습니다.
