#!/usr/bin/env python3
"""
교과 팩 적합성 검사 (Subject Pack Conformance Check)

asa-skills 엔진이 subject/ 를 인식할 수 있는지 검증한다.
다른 교과로 포크한 뒤 이 스크립트가 통과해야 스킬이 정상 동작한다.

    python scripts/validate_subject.py
    python scripts/validate_subject.py --strict   # 경고도 실패로 처리

FORKING.md 참조.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SUBJECT_DIR = ROOT / "subject"
CORE_DIR = ROOT / "core"
SKILLS_DIR = ROOT / "skills"

ENGINE_SCHEMA_VERSION = 1

# core/asa-rules.md 에 명시된 제도 규칙. subject.yaml 이 이와 어긋나면 안 된다.
CANONICAL_TARGETS = {
    "selected_response.target_correct_rate": 0.66,
    "constructed_response.target_full_mark_prob": 0.50,
}
VALID_LEVEL_SYSTEMS = {3, 5}
REQUIRED_DOCS = ("difficulty_levers", "item_conventions", "misconceptions")

errors: list[str] = []
warnings: list[str] = []


def err(msg: str) -> None:
    errors.append(msg)


def warn(msg: str) -> None:
    warnings.append(msg)


def load_yaml(path: Path):
    try:
        import yaml
    except ImportError:
        print("PyYAML 이 필요합니다:  pip install pyyaml", file=sys.stderr)
        sys.exit(2)
    with path.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)


# ── 1. 디렉터리·파일 존재 ────────────────────────────────────────────────
def check_layout() -> dict | None:
    if not SUBJECT_DIR.is_dir():
        err("subject/ 디렉터리가 없습니다. 교과 팩이 설치되지 않았습니다.")
        return None

    manifest = SUBJECT_DIR / "subject.yaml"
    if not manifest.is_file():
        err("subject/subject.yaml 이 없습니다. 교과 팩의 계약 파일입니다.")
        return None

    data = load_yaml(manifest)
    if not isinstance(data, dict):
        err("subject/subject.yaml 을 매핑으로 읽을 수 없습니다.")
        return None
    return data


# ── 2. 스키마 버전·필수 블록 ─────────────────────────────────────────────
def check_schema(data: dict) -> None:
    ver = data.get("schema_version")
    if ver is None:
        err("schema_version 이 없습니다.")
    elif ver != ENGINE_SCHEMA_VERSION:
        err(
            f"schema_version 불일치: 팩={ver}, 엔진={ENGINE_SCHEMA_VERSION}. "
            "upstream 을 merge 하거나 팩을 갱신하세요."
        )

    for key in ("subject", "standard_code", "courses", "assessment", "documents"):
        if key not in data:
            err(f"필수 블록 누락: {key}")

    subj = data.get("subject") or {}
    for key in ("id", "name_ko"):
        if not subj.get(key):
            err(f"subject.{key} 가 비어 있습니다.")


# ── 3. 성취기준 코드 정규식 ──────────────────────────────────────────────
def check_standard_code(data: dict) -> re.Pattern | None:
    sc = data.get("standard_code") or {}
    raw = sc.get("pattern")
    if not raw:
        err("standard_code.pattern 이 없습니다.")
        return None
    try:
        rx = re.compile(raw)
    except re.error as exc:
        err(f"standard_code.pattern 이 올바른 정규식이 아닙니다: {exc}")
        return None

    missing = [g for g in ("band", "course", "area", "serial") if g not in rx.groupindex]
    if missing:
        err(
            f"standard_code.pattern 에 명명 그룹이 없습니다: {', '.join(missing)}. "
            "엔진은 (?P<band>…)(?P<course>…)(?P<area>…)(?P<serial>…) 로 코드를 파싱합니다."
        )

    examples = sc.get("examples") or []
    if not examples:
        warn("standard_code.examples 가 없습니다. 정규식을 검증할 수 없습니다.")
    for ex in examples:
        if not rx.match(str(ex)):
            err(f"standard_code.examples 의 '{ex}' 가 pattern 과 맞지 않습니다.")
    return rx


# ── 4. 과목 목록 ─────────────────────────────────────────────────────────
def check_courses(data: dict, rx: re.Pattern | None) -> list[dict]:
    courses = data.get("courses") or []
    if not courses:
        err("courses 가 비어 있습니다.")
        return []

    seen_ids, seen_tokens = set(), set()
    for i, c in enumerate(courses):
        label = c.get("name") or c.get("id") or f"courses[{i}]"

        for key in ("id", "code_token", "code_example", "name", "level_system", "grading_scale"):
            if c.get(key) in (None, ""):
                err(f"{label}: 필수 항목 '{key}' 누락")

        if c.get("id") in seen_ids:
            err(f"{label}: course id 중복 — {c.get('id')}")
        seen_ids.add(c.get("id"))

        token = c.get("code_token")
        if token in seen_tokens:
            err(f"{label}: code_token 중복 — {token}")
        seen_tokens.add(token)

        for key in ("level_system", "grading_scale"):
            val = c.get(key)
            if val is not None and val not in VALID_LEVEL_SYSTEMS:
                err(f"{label}: {key}={val} 은 허용되지 않습니다 (3 또는 5).")

        if "has_area_levels" not in c:
            err(f"{label}: has_area_levels 누락. 학기 단위 성취수준 생성에 필수입니다.")
        elif c["has_area_levels"] and not c.get("areas"):
            err(f"{label}: has_area_levels=true 인데 areas 가 비어 있습니다.")

        if c.get("grading_scale_verified") is False:
            warn(f"{label}: grading_scale 미확인 상태입니다. 학교생활기록부 기재요령으로 확인하세요.")

        # code_example 이 pattern 과 맞고, 그 course 그룹이 code_token 과 일치하는지.
        # (코드 형식은 과목 유형마다 다를 수 있으므로 조립하지 않고 실제 예시로 검증한다.)
        example = c.get("code_example")
        if rx and example:
            m = rx.match(str(example))
            if not m:
                err(f"{label}: code_example '{example}' 이 standard_code.pattern 과 맞지 않습니다.")
            elif token and m.groupdict().get("course") != token:
                err(
                    f"{label}: code_example '{example}' 에서 파싱된 과목 토큰 "
                    f"'{m.groupdict().get('course')}' 이 code_token '{token}' 과 다릅니다."
                )

    return courses


# ── 5. 평가 관행이 제도 규칙과 일치하는가 ────────────────────────────────
def check_assessment(data: dict) -> None:
    paper = ((data.get("assessment") or {}).get("paper")) or {}
    probes = {
        "selected_response.target_correct_rate":
            (paper.get("selected_response") or {}).get("target_correct_rate"),
        "constructed_response.target_full_mark_prob":
            (paper.get("constructed_response") or {}).get("target_full_mark_prob"),
    }
    for key, actual in probes.items():
        expected = CANONICAL_TARGETS[key]
        if actual is None:
            err(f"assessment.paper.{key} 가 없습니다.")
        elif abs(float(actual) - expected) > 1e-9:
            err(
                f"assessment.paper.{key}={actual} 이 core/asa-rules.md 의 "
                f"제도 규칙({expected})과 다릅니다. 제도 규칙은 교과가 바꿀 수 없습니다."
            )


# ── 6. 교과 특수 문서 3종 ────────────────────────────────────────────────
def check_documents(data: dict) -> None:
    docs = data.get("documents") or {}
    for key in REQUIRED_DOCS:
        name = docs.get(key)
        if not name:
            err(f"documents.{key} 가 지정되지 않았습니다.")
            continue
        path = SUBJECT_DIR / name
        if not path.is_file():
            err(f"documents.{key} → {name} 파일이 없습니다.")
        elif path.stat().st_size < 200:
            err(f"{name} 이 사실상 비어 있습니다 ({path.stat().st_size}B). 교과 팩이 미완성입니다.")


# ── 7. 빌드된 데이터 (있으면 검사) ───────────────────────────────────────
# 합성되지 못하고 남은 한글 조합용 자모 (build_refs.py 와 동일 기준)
STRAY_JAMO_RE = re.compile(r"[ᄀ-ᇿꥠ-꥿ힰ-퟿]")


def check_data(data: dict, rx: re.Pattern | None, courses: list[dict]) -> None:
    std_dir = SUBJECT_DIR / "data" / "standards"
    files = sorted(std_dir.glob("*.json")) if std_dir.is_dir() else []
    if not files:
        warn("subject/data/standards/ 가 비어 있습니다. `python scripts/build_refs.py` 를 먼저 실행하세요.")
        return

    import json

    expected = {c["id"]: c for c in courses if c.get("id")}
    for path in files:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            err(f"{path.name}: JSON 파싱 실패 — {exc}")
            continue

        course = expected.get(payload.get("course_id"))
        if course is None:
            err(f"{path.name}: subject.yaml 에 없는 course_id — {payload.get('course_id')}")
            continue

        want = int(course["level_system"])
        for std in payload.get("standards", []):
            code = std.get("code", "")
            if rx and not rx.match(code):
                err(f"{path.name}: 성취기준 코드가 pattern 과 맞지 않습니다 — {code}")
            levels = std.get("levels") or {}
            if len(levels) != want:
                err(
                    f"{path.name} {code}: 수준 진술 {len(levels)}개 "
                    f"(level_system={want} 이므로 {want}개여야 함)"
                )
            for name, text in levels.items():
                if not str(text).strip():
                    err(f"{path.name} {code}: 수준 {name} 진술문이 비어 있습니다.")

        # 합성되지 못한 한글 조합용 자모 — 원본 조판의 옛한글이 그대로 남은 경우.
        # 예: '있ᅌᅳᆷ을'(= 있음을). 출력물에 그대로 나가면 진술문이 깨져 보인다.
        stray = STRAY_JAMO_RE.findall(path.read_text(encoding="utf-8"))
        if stray:
            err(
                f"{path.name}: 합성되지 않은 한글 자모 {len(stray)}건 — "
                "scripts/build_refs.py 의 ARCHAIC_JAMO 에 해당 자모를 추가하고 다시 빌드하세요."
            )


# ── 8. 엔진 순수성 — 교과 지식이 core/·skills/ 로 새지 않았는가 ──────────
def check_engine_purity(data: dict, courses: list[dict]) -> None:
    terms: set[str] = set()
    for c in courses:
        for val in (c.get("name"), c.get("code_token")):
            if val and len(str(val)) >= 3:      # 짧은 일반어(예: '문학')는 오탐이 많아 제외
                terms.add(str(val))
    subj_name = (data.get("subject") or {}).get("name_ko")
    if subj_name:
        terms.add(subj_name)

    if not terms:
        return

    for base in (CORE_DIR, SKILLS_DIR):
        if not base.is_dir():
            continue
        for path in base.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in {".md", ".py", ".yaml", ".yml"}:
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            for term in sorted(terms):
                if term in text:
                    warn(
                        f"엔진 순수성: {path.relative_to(ROOT)} 에 교과 고유어 '{term}' 이 있습니다. "
                        "subject/ 로 옮기는 것을 검토하세요."
                    )


# ── 0. 미완성 표지(TODO) ────────────────────────────────────────────────
def check_todos() -> None:
    """템플릿에서 갈아끼운 뒤 채우지 않은 자리를 먼저 잡는다."""
    hits: list[tuple[str, int, str]] = []
    for path in sorted(SUBJECT_DIR.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in {".md", ".yaml", ".yml"}:
            continue
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (UnicodeDecodeError, OSError):
            continue
        rel = str(path.relative_to(ROOT))
        for i, line in enumerate(lines, 1):
            if "TODO" in line:
                hits.append((rel, i, line.strip()[:70]))

    if not hits:
        return

    by_file: dict[str, int] = {}
    for rel, _, _ in hits:
        by_file[rel] = by_file.get(rel, 0) + 1

    err(f"교과 팩이 미완성입니다 — TODO {len(hits)}곳이 남아 있습니다.")
    for rel, n in sorted(by_file.items()):
        errors.append(f"    · {rel}: {n}곳")
    for rel, ln, text in hits[:5]:
        errors.append(f"      {rel}:{ln}  {text}")
    if len(hits) > 5:
        errors.append(f"      … 외 {len(hits) - 5}곳. FORKING.md 를 참조해 채우세요.")


def main() -> int:
    # Windows 콘솔(cp949)에서도 한글이 깨지지 않도록 강제한다.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    ap = argparse.ArgumentParser(description="교과 팩 적합성 검사")
    ap.add_argument("--strict", action="store_true", help="경고도 실패로 처리")
    args = ap.parse_args()

    data = check_layout()
    if data is not None:
        check_todos()
        check_schema(data)
        rx = check_standard_code(data)
        courses = check_courses(data, rx)
        check_assessment(data)
        check_documents(data)
        check_data(data, rx, courses)
        check_engine_purity(data, courses)

    subj = (data or {}).get("subject") or {}
    print(f"교과 팩 검사  —  id={subj.get('id', '?')}  ({subj.get('name_ko', '?')})")
    print("-" * 60)

    for w in warnings:
        print(f"  [경고] {w}")
    for e in errors:
        print(f"  [오류] {e}")

    if not errors and not warnings:
        print("  이상 없음.")
    print("-" * 60)
    print(f"오류 {len(errors)}건, 경고 {len(warnings)}건")

    if errors:
        return 1
    if warnings and args.strict:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
