# 인터뷰 질문 검증

## 변경과 자동 검사

기존 live 질문 요청에는 `target_field`와 문맥만 전달되어 `QUESTIONS`의 대상별
기본 질문이 빠져 있었다. `Engine.question()`은 이제 `default_question`과
`question_guidance`를 함께 전달한다. 선택·배치는 직접 수정과 구분하며 AI 도구 안의
후보 선택·구성도 포함한다. 기존 진술의 반복 확인을 피하고, 작업 없음 답변과 첨부·이미지의
해석 한계를 명시한다. 공용 `QUESTIONS`의 변경은 mock, 무근거 질문, 분석 및 Brief에도 적용된다.

자동 테스트는 HTTP 채팅 요청의 대상별 지침·기본 질문, human_edit 진술만 있는 문맥,
500자 제한, 고정 질문, 잘못된 대상·위조 출처 차단과 분석·Brief 회귀를 검사한다.
미리 정한 모델 응답을 사용하는 테스트는 요청 구성과 검증 경로를 확인할 뿐,
실제 생성 질문의 의미 품질을 보장하지 않는다. 응답 단어 필터는 추가하지 않았다.

## 실제 llama.cpp 비교 (2026-11-10)

설정된 `/v1/models`가 HTTP 200으로 응답했고 `idea2ip-vl` 모델을 확인했다.
`samples/project.json`에서 `statement-edit`만 남겼다. 입력 진술은
“제가 편집 프로그램에서 캐릭터 눈의 모양을 직접 다시 그렸습니다.”이며,
검색 없이 live 모드로 각 대상을 한 번씩 호출했다. temperature는 기존 값 0이다.

최종 지침으로 받은 질문 원문:

| 대상 | 실제 질문 | source_ids |
|---|---|---|
| human_edit | 캐릭터 눈의 모양을 직접 다시 그린 부분이 있다면, 그 작업의 구체적인 방법이나 도구는 무엇이었나요? 없으면 '없다'고 알려주세요. | statement-edit |
| selection_arrangement | 캐릭터의 눈 모양이나 다른 요소를 선택하거나 배치하는 작업을 직접 수행했는지, 또는 특정 기준에 따라 구성했는지 알려주세요. 없으면 '없다'고 답해도 됩니다. | statement-edit |
| creative_intent | 표현하려던 의도가 있나요? 있다면 그 의도와 이를 반영한 결정이나 과정을, 없다면 '없다'고 알려주세요. | 없음 |

수정 중 첫 비교에서는 선택·배치를 눈 수정 과정에 연결하는 질문이 나와 별개의 작업 유무를
묻는 지침을 보강했다. 최종 비교에서는 선택·배치 작업의 존재를 전제하지 않고 없음 답변을
명시했으며, 의도 질문도 수정 방법과 구분됐다. 다만 선택·배치에 눈 모양을 예로 드는
문맥 편향과 human_edit의 “있다면”이라는 불필요한 조건절은 남았다. 출처 ID가 붙어도
사용자 진술을 참조한다는 뜻이며 해당 작업의 독립적인 증명이 아니다.

이는 한 문맥에서의 제한적인 실제 모델 확인이다. 다양한 문맥, 이미지·첨부, 부정·상충 진술과
반복 실행 전반에서 의미 품질이 보장된다는 결론은 내리지 않는다.

## Ubuntu 재현

기존 llama.cpp를 실행한 상태에서 저장소 루트에서 실행한다. `.env`의 모델 주소와 이름을
사용하며 DB나 검색 설정을 변경하지 않고 이 비교 호출에서만 검색을 비활성화한다.

```bash
source .venv/bin/activate
python - <<'PY'
from pathlib import Path
from idea2ip.config import Settings
from idea2ip.engine import Engine
from idea2ip.models import ProjectContext, QuestionRequest

engine = Engine(Settings(mode="live", retrieval="none", llm_timeout=60))
context = ProjectContext.model_validate_json(Path("samples/project.json").read_text())
context.sources = [s for s in context.sources if s.source_id == "statement-edit"]
for target in ("human_edit", "selection_arrangement", "creative_intent"):
    result = engine.question(QuestionRequest(context=context, target_field=target))
    print(result.model_dump_json(indent=2))
PY
```

회귀 검사:

```bash
python -m pytest -q
python -m ruff check .
python -m ruff format --check .
```

## 이미지 관찰과 질문 연결 개선 (2026-11-10)

`Engine.question()` → `LlamaClient.generate()` → `/chat/completions`를 확인했다.
검색 후 `context.model_dump(mode="json")`가 `DATA_JSON` 안에 그대로 들어가므로
`IMAGE_OBSERVATION`의 내용, 타입, `source_id`, `parent_source_ids`와 부모 첨부가
실제 채팅 요청까지 전달된다. 데이터 전달 누락은 확인되지 않았다.
기존 관찰 지침은 색·형태·배치와 추론 금지만 짧게 제시했고, 질문 지침에는 관찰을
구체적으로 활용하는 방법과 활용한 관찰의 출처 반환 조건이 부족했다.

관찰 지침에 주요 요소별 간결한 설명, 반복·개수 채우기 금지, 재질·개폐 상태·가려진
구조의 불확실성 표현을 추가했다. limitations는 실제 판독 한계만 기록하며 빈 목록을
허용한다. 관찰 응답의 observations와 limitations에서 완전히 같은 항목만 순서를
유지하며 제거한다. 사용자 진술은 이 처리 대상이 아니다.

기본 질문과 대상별 QUESTION_GUIDANCE를 유지하고, 활용 가능한 관찰이 있을 때
시각 요소를 대상에 맞는 질문의 계기로 쓰도록 보강했다. 직접 수정·배치 작업 유무를
열어 두며 창작 의도를 이미지로 추정하지 않는다. 관찰은 오류가 가능한 모델 해석이다.
실제 활용한 관찰의 source_id를 반환하도록 안내하고 일반 질문에는 출처를 강제하지
않는다. 사용자 진술로 이미 답한 내용은 반복하지 않는다.

`tests/test_image_questions.py`는 실제 HTTP 요청 본문, 관찰 인용·위조 출처 차단,
빈 관찰·관찰 없음·mock, 관찰 중복 제거·사용자 원문 보존, 이미지 단독 분석·Brief 및
관찰을 사용자 기여로 인용하려는 응답의 차단을 확인한다. 고정 응답 테스트는 요청 구성과
검증 경로만 확인한다. 실제 관찰 정확도나 질문 의미 품질의 증거가 아니다.

최종 검사: `python -m pytest -q`는 99 passed(기존 Starlette 지원 중단 경고 1건),
`python -m ruff check .`와 `python -m ruff format --check .`는 통과했다.
기존 분석·Brief 회귀와 출처·프로젝트·스냅샷 격리 검사를 포함한다.

### 실제 모델 확인 결과

`~/idea2ip-rag/image.png`는 존재하며 직접 확인했다. 설정된 모델 주소
`http://localhost:8081/v1`의 `/models` 연결은 ConnectError였고 실제
`Engine.observe()` 호출도 `MODEL_UNAVAILABLE`로 실패했다. mock으로 대체하지 않았다.
따라서 실제 모델의 관찰 및 질문 3종 품질 검증은 **수행하지 못했다**.
요청 파일(이미지 base64 포함)과 실패 결과는 git에서 제외되는
`build/image-quality/observe-request.json`, `build/image-quality/status.json`에만 저장했다.
원래 미추적 상태의 이미지와 Zone.Identifier 파일은 보존했으며 커밋·푸시하지 않았다.

### Ubuntu 이미지 재확인

저장소 루트에서 기존 llama.cpp 서버를 실행한 뒤 아래를 실행한다. `.env`의 모델 설정을
사용하고 이 확인에서만 live 모드·검색 없음으로 실행한다. 사용자 진술을 넣지 않아
이미지 기반 질문을 분리해서 확인할 수 있다. 응답 파일을 열어 관찰 정확성, 전제 없는
질문, 실제 활용한 관찰 출처를 확인한다. 서버 실패 시 오류 코드만 출력하며 종료한다.

```bash
source .venv/bin/activate
test -f "$HOME/idea2ip-rag/image.png"
python - <<'PY'
import base64
from pathlib import Path

from idea2ip.config import Settings
from idea2ip.engine import Engine
from idea2ip.errors import ServiceError
from idea2ip.models import ImageRequest, ProjectContext, QuestionRequest, Source

out = Path("build/image-quality")
out.mkdir(parents=True, exist_ok=True)
image = Path.home() / "idea2ip-rag/image.png"
context = ProjectContext(
    project_id="image-quality-check", title="이미지 인터뷰 확인",
    sources=[Source(
        source_id="attachment-image", project_id="image-quality-check",
        kind="ATTACHED_FILE", title="테스트 이미지",
        content="사용자가 첨부한 이미지 파일. 창작 과정 진술 없음.",
    )],
)
engine = Engine(Settings(mode="live", retrieval="none"))
try:
    request = ImageRequest(
        context=context, attachment_source_id="attachment-image",
        image_data_uri="data:image/png;base64," + base64.b64encode(image.read_bytes()).decode(),
    )
    (out / "observe-request.json").write_text(request.model_dump_json(indent=2), encoding="utf-8")
    observed = engine.observe(request)
    (out / "observation.json").write_text(observed.model_dump_json(indent=2), encoding="utf-8")
    context.sources.append(Source(
        source_id=observed.source_id, project_id=context.project_id,
        kind=observed.evidence_type, title="모델 이미지 관찰",
        content=observed.model_dump_json(), parent_source_ids=observed.parent_source_ids,
    ))
    for target in ("human_edit", "selection_arrangement", "creative_intent"):
        request = QuestionRequest(context=context, target_field=target)
        (out / f"{target}-request.json").write_text(request.model_dump_json(indent=2), encoding="utf-8")
        question = engine.question(request)
        (out / f"{target}.json").write_text(question.model_dump_json(indent=2), encoding="utf-8")
    print("관찰 및 질문 3종 저장:", out)
except ServiceError as exc:
    raise SystemExit(f"{exc.code}: {exc.message}") from None
PY
python -m pytest -q
python -m ruff check .
python -m ruff format --check .
```
