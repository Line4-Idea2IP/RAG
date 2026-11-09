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
