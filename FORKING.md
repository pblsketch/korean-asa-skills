# 다른 교과로 포크하기

이 저장소는 **국어과** 버전이다. 수학·영어·사회·과학 등 다른 교과 버전은 이 저장소를 **포크해서** 만든다.

성취평가제의 제도 규칙(성취율, 분할점수, MCP, 2/3·50% 규칙 등)은 교과와 무관하므로 그대로 물려받고, **교과 지식만 갈아끼운다.**

---

## 설계 규칙: 건드리는 곳은 한 군데뿐

```
asa-skills/
├── skills/           ← ✋ 건드리지 않는다 (엔진)
├── core/             ← ✋ 건드리지 않는다 (제도 규칙 · 양식)
├── scripts/          ← ✋ 건드리지 않는다
├── subject-template/ ← ✋ 건드리지 않는다 (빈 교과 팩)
│
└── subject/          ← ✅ 이 디렉터리만 통째로 교체한다
```

이 규칙을 지키면 **upstream의 엔진 개선을 계속 받아올 수 있다.**

```bash
git remote add upstream https://github.com/<원본>/asa-skills.git
git fetch upstream
git merge upstream/main        # subject/ 만 고쳤다면 충돌이 나지 않는다
```

`core/`나 `skills/`를 고쳐야만 해결되는 문제를 발견했다면, 그건 **엔진의 버그이거나 교과 팩 스키마의 한계**다. 포크에서 땜질하지 말고 upstream에 이슈로 올려 달라. 그래야 모든 교과가 함께 고쳐진다.

---

## 절차

### 1. 포크하고 교과 팩을 초기화한다

```bash
git clone https://github.com/<본인>/asa-skills-math.git
cd asa-skills-math
python scripts/init_subject.py --id math --name "수학과" --en "Mathematics"
```

`subject/`가 `subject-template/` 상태로 초기화되고, 채워야 할 TODO 개수와 순서가 표시된다.
기존 `subject/`는 `subject.bak-<타임스탬프>`로 백업되므로 국어과 팩을 참고용으로 계속 볼 수 있다.

진행 상황은 언제든 검증기로 확인한다. 미완성이면 남은 TODO를 파일별로 짚어 준다.

```bash
python scripts/validate_subject.py
```

### 2. `subject/subject.yaml`을 채운다

교과 팩의 **계약**이다. 엔진은 이 파일만 보고 교과를 인식한다.

| 블록 | 채울 내용 |
|---|---|
| `subject` | 교과 id·이름·교육과정·학교급 |
| `standard_code` | **성취기준 코드 정규식.** 예: 국어 `[10공국1-01-01]` → 수학 `[10공수1-01-01]` |
| `courses` | 과목 목록. 각 과목의 `level_system`(성취수준 체계 5/3), `grading_scale`(성취도 평정 단계), `has_area_levels`(영역별 성취수준 개발 여부), `areas` |
| `jurisdiction` | 시도교육청 지침. 교과와 독립된 축이므로 이 블록만 따로 교체해도 된다 |
| `assessment` | 문항 유형별 관행. `target_*` 값은 `core/asa-rules.md`와 일치해야 한다 |
| `sources` | 원자료 목록. `scripts/build_refs.py`가 참조한다 |

> ⚠ **`has_area_levels` 는 과목마다 실제 자료를 열어 확인할 것.**
> 판단 기준은 공통/선택이 아니라 **내용 영역 구분의 유무**다. KICE 보급본은 "고등학교 선택과목의 경우, 교과(과목)별 내용 체계의 특성에 따라 **영역 구분이 없는 과목**(국어, 영어 등)에서는 '영역별 성취수준'이 없음"이라고 밝힌다.
> 국어과는 선택과목 9종 모두 영역 구분이 없어 `false` 지만, **다른 교과는 선택과목에도 영역별 성취수준이 있을 수 있다.**
> 이 값이 틀리면 학기 단위 성취수준 생성 로직이 없는 입력을 찾거나, 있는 재료를 놓친다.

### 3. 교과 특수 문서 3종을 쓴다

| 파일 | 내용 | 난이도 |
|---|---|---|
| `difficulty-levers.md` | **성취수준을 가르는 교과별 변수** | ★★★ 가장 어렵고 가장 중요 |
| `item-conventions.md` | 문항 형식·지문·발문 관행 | ★★ |
| `misconceptions.md` | 오답·오개념 패턴 (결과 분석용) | ★★ |

`difficulty-levers.md`가 교과 팩의 품질을 좌우한다. 국어과 버전(`subject/difficulty-levers.md`)의 §5에 **도출 절차**가 적혀 있으니 그대로 따르면 된다. 요약하면:

1. 해당 교과의 **같은 성취기준을 재는 A~E 5문항**을 나란히 놓는다
2. 인접 수준 쌍마다 "무엇이 달라졌는가"를 적는다
3. 반복되는 차이를 레버로 이름 붙인다 (보통 4~6개)
4. **E 수준의 바닥이 어디인지** 반드시 명시한다

> `skills/asa-item`의 **부트스트랩 모드**가 1~3단계를 반자동으로 해 초안을 만들어 준다.
> ```
> /asa-item bootstrap --standard "[10공수1-01-02]" --items <A~E 문항 세트 파일>
> ```

### 4. 원자료를 넣고 데이터를 빌드한다

저작권 때문에 **성취수준 원문과 예시문항은 저장소에 포함하지 않는다.** 각자 로컬에 두고 빌드한다.

```bash
# 교육부·KICE 성취수준 보급본을 로컬에 내려받아 둔 뒤
python scripts/build_refs.py
python scripts/validate_subject.py
```

빌드 결과는 `subject/data/`에 생성되며 `.gitignore` 처리되어 있다.

**자료 입수처**
- 한국교육과정평가원 성취수준 보급본 — 교과별로 발간되어 있다
- 각 시도교육청 성취평가 표준화 평가도구 — 교과별 발간
- [KICE 학생평가지원포털](https://stas.moe.go.kr) — 로그인 필요, `.env` 설정 후 `scripts/stas_fetch.py`

### 5. 검증한다

```bash
python scripts/validate_subject.py
```

통과 조건:
- `subject.yaml`이 스키마를 만족하고 `schema_version`이 엔진과 호환됨
- 문서 3종이 모두 존재하고 비어 있지 않음
- `courses[]`의 모든 `code_token`이 `standard_code.pattern`과 정합
- `subject/data/standards/`의 성취기준 코드가 전부 파싱되고, 각 성취기준에 `level_system` 수만큼의 수준 진술이 존재
- `assessment.target_*` 값이 `core/asa-rules.md`와 불일치하지 않음

---

## 최종 점검: 엔진이 정말 교과 중립인가

교과 팩을 다 만들었다면 이 테스트를 해 보라.

```bash
mv subject subject.bak && python scripts/validate_subject.py
# → "subject/ 없음" 오류만 나야 한다.
#    core/ 나 skills/ 에서 교과 관련 오류가 나오면 엔진에 교과 지식이 새어 들어간 것이다.
```

이 경우 upstream에 이슈를 올려 달라.

---

## 저작권

`core/`와 `skills/`, 문서 3종은 이 저장소의 저작물이다.

`subject/data/`에 빌드되는 성취수준 원문과 예시문항은 **교육부·한국교육과정평가원·시도교육청의 저작물**이다. 포크한 저장소에도 이를 커밋하지 말 것. `.gitignore`가 기본으로 막고 있다.

> 해당 자료가 **공공누리 제1유형(출처표시)** 으로 공개된 것이 확인되면, 출처를 명시하고 `.gitignore`에서 `subject/data/`를 제외해 함께 배포할 수 있다. 원문 표지·판권면의 공공누리 마크를 확인하라.
