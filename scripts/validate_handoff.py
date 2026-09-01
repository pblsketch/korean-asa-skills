#!/usr/bin/env python3
"""
인계 파일 검증 (Handoff Validator)

스킬 사이를 잇는 인계 파일이 규약대로 만들어졌는지 검사한다.

    python scripts/validate_handoff.py              # 전부
    python scripts/validate_handoff.py --plan       # .work/plan/ 만
    python scripts/validate_handoff.py --items      # .work/items/ 만

    .work/plan/<과목id>_<학기>.json    asa-guide → asa-item
    .work/items/<성취기준코드>.json     asa-item  → asa-analyze

**각 스킬의 마지막 단계에서 이걸 돌린다.** 오류가 하나라도 있으면 작업이 끝난 것이 아니다.

왜 스크립트인가 — 인계는 지시문 끝에 한 줄로 적혀 있으면 놓친다. 실제로 놓쳤다.
사람이 기억하는 대신 기계가 막는다.

검사 범위는 **인계 파일뿐**이다. 산출 문서(마크다운·HWP)는 보지 않는다.
Range≠Target 이나 부사어 위계 같은 것은 구조화되어 있지 않아 오탐이 많기 때문이다.
그 판단은 사람이 한다.

  [오류]  산출을 막는다. 명백히 규약 위반이거나 다음 스킬이 못 읽는다
  [경고]  진행은 되지만 확인이 필요하다
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SUBJECT_DIR = ROOT / "subject"
PLAN_DIR = ROOT / ".work" / "plan"
ITEMS_DIR = ROOT / ".work" / "items"
LEVELS = ("A", "B", "C", "D", "E")

errors: list[str] = []
warnings: list[str] = []


def err(msg: str) -> None:
    errors.append(msg)


def warn(msg: str) -> None:
    warnings.append(msg)


def load_conf() -> dict:
    try:
        import yaml
    except ImportError:
        sys.exit("PyYAML 이 필요합니다:  pip install pyyaml")
    path = SUBJECT_DIR / "subject.yaml"
    if not path.is_file():
        sys.exit(f"{path} 가 없습니다.")
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def load_standards() -> dict[str, dict]:
    d = SUBJECT_DIR / "data" / "standards"
    out: dict[str, dict] = {}
    for p in sorted(d.glob("*.json")) if d.is_dir() else []:
        try:
            out[p.stem] = json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
    return out


# ── .work/plan/ ────────────────────────────────────────────────────────
def check_plan(path: Path, conf: dict, standards: dict[str, dict]) -> None:
    name = path.name
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        err(f"{name}: JSON 파싱 실패 — {exc}")
        return

    course_id = d.get("course_id")
    course = next((c for c in conf.get("courses", []) if c["id"] == course_id), None)
    if course is None:
        err(f"{name}: subject.yaml 에 없는 course_id — {course_id}")
        return
    doc = standards.get(course_id)

    if not re.fullmatch(r"\d{4}-[12]", str(d.get("semester", ""))):
        warn(f"{name}: semester 가 'YYYY-1' 형식이 아닙니다 — {d.get('semester')!r}")

    # 성취기준 — 실재하는 코드인가
    codes = d.get("standards") or []
    if not codes:
        err(f"{name}: standards 가 비어 있습니다. 편성 성취기준을 적어야 합니다.")
    known = {s["code"] for s in (doc or {}).get("standards", [])}
    if known:
        unknown = [c for c in codes if c not in known]
        if unknown:
            err(f"{name}: {course_id} 에 없는 성취기준 — {', '.join(unknown[:5])}")

    # 학기 단위 성취수준 — 라벨+본문 배열인가
    sem = d.get("semester_levels") or {}
    if sem:
        want = int(course.get("level_system", 5))
        present = [lv for lv in LEVELS[:want] if sem.get(lv)]
        missing = [lv for lv in LEVELS[:want] if not sem.get(lv)]
        if missing:
            err(f"{name}: 학기 단위 성취수준에 {', '.join(missing)} 수준이 없습니다 "
                f"(level_system={want}).")

        labels_by_level = {}
        for lv in present:
            entries = sem[lv]
            if not isinstance(entries, list):
                err(f"{name}: semester_levels.{lv} 가 배열이 아닙니다. "
                    "라벨+본문 배열 [{'label':…,'text':…,'summary':…}] 이어야 합니다.")
                continue
            labels = []
            for i, e in enumerate(entries):
                if not isinstance(e, dict) or not e.get("label") or not e.get("text"):
                    err(f"{name}: semester_levels.{lv}[{i}] 에 label 또는 text 가 없습니다.")
                    continue
                labels.append(e["label"])
                if not e.get("summary"):
                    warn(f"{name}: semester_levels.{lv}[{e['label']}] 에 summary 가 없습니다. "
                         "asa-item 이 다른 영역을 훑을 때 씁니다.")
            labels_by_level[lv] = labels

        # 수준마다 라벨 집합이 같아야 한다 — 다르면 어느 수준에서 영역이 빠진 것이다
        sets = {lv: tuple(v) for lv, v in labels_by_level.items() if v}
        if len(set(sets.values())) > 1:
            err(f"{name}: 수준마다 라벨 구성이 다릅니다 — "
                + " / ".join(f"{lv}:{len(v)}개" for lv, v in sets.items()))

        # 영역 프레임이면 라벨이 subject.yaml 의 영역명과 맞아야 한다
        areas = set((course.get("areas") or {}).values())
        if areas and sets:
            first = set(next(iter(sets.values())))
            if first and first <= areas and first != areas:
                warn(f"{name}: 영역 {', '.join(sorted(areas - first))} 이(가) "
                     "학기 단위 성취수준에 없습니다. 편성 범위가 맞는지 확인하세요.")

    # 평가 요소 — 편성 성취기준에만 달려 있는가
    for c in (d.get("elements") or {}):
        if codes and c not in codes:
            warn(f"{name}: elements 에 편성되지 않은 성취기준 {c} 가 있습니다.")

    # 반영 비율 — 합이 100 인가
    plan = d.get("assessment_plan") or {}
    ratios = []
    for group in ("지필", "수행"):
        for key, v in (plan.get(group) or {}).items():
            r = (v or {}).get("반영비율")
            if r is not None:
                ratios.append((f"{group}/{key}", r))
    if ratios:
        total = sum(r for _, r in ratios)
        if abs(total - 100) > 1e-6:
            err(f"{name}: 반영 비율 합이 {total}% 입니다 (100% 여야 합니다) — "
                + ", ".join(f"{k} {r}" for k, r in ratios))
    if plan and "서논술형_반영비율" not in plan:
        warn(f"{name}: assessment_plan 에 서논술형_반영비율 키가 없습니다. "
             "모르면 null 로 두되 키는 남기세요(확인이 필요하다는 표시).")

    if d.get("cut_score_method") not in (None, "고정", "추정"):
        err(f"{name}: cut_score_method 는 '고정' 또는 '추정' 이어야 합니다 — "
            f"{d.get('cut_score_method')!r}")


# ── .work/items/ ───────────────────────────────────────────────────────
DIFFICULTY_ORDER = {"쉬움": 0, "보통": 1, "어려움": 2}


def check_items(path: Path, conf: dict, standards: dict[str, dict]) -> None:
    name = path.name
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        err(f"{name}: JSON 파싱 실패 — {exc}")
        return

    course_id = d.get("course_id")
    course = next((c for c in conf.get("courses", []) if c["id"] == course_id), None)
    if course is None:
        err(f"{name}: subject.yaml 에 없는 course_id — {course_id}")
        return

    code = d.get("code")
    doc = standards.get(course_id)
    if doc and code not in {s["code"] for s in doc.get("standards", [])}:
        err(f"{name}: {course_id} 에 없는 성취기준 — {code}")

    want = int(course.get("level_system", 5))
    mcp = d.get("mcp") or {}
    missing = [lv for lv in LEVELS[:want] if not mcp.get(lv)]
    if missing:
        err(f"{name}: MCP 수행 특성에 {', '.join(missing)} 가 없습니다. "
            "각 문항의 출제 범위를 정하는 근거이므로 전 수준이 필요합니다.")

    items = d.get("items") or []
    if not items:
        err(f"{name}: items 가 비어 있습니다.")
        return

    for i, it in enumerate(items):
        for key in ("no", "target_level", "difficulty", "points", "answer"):
            if it.get(key) in (None, ""):
                err(f"{name}: items[{i}] 에 {key} 가 없습니다."
                    + ("  예상 난이도가 없으면 asa-analyze 가 갭을 못 봅니다."
                       if key == "difficulty" else ""))
        if it.get("difficulty") not in DIFFICULTY_ORDER and it.get("difficulty"):
            warn(f"{name}: items[{i}] 의 difficulty 가 '쉬움/보통/어려움' 이 아닙니다 — "
                 f"{it['difficulty']!r}")

    nos = [it.get("no") for it in items]
    if len(set(nos)) != len(nos):
        err(f"{name}: 문항 번호가 중복됩니다 — {nos}")

    # R7 수준 역전 — 상위 수준 문항이 하위보다 쉬우면 분할점수 전제가 깨진다
    rank = {lv: i for i, lv in enumerate(reversed(LEVELS[:want]))}   # E=0 … A=4
    graded = [(it["target_level"], DIFFICULTY_ORDER.get(it.get("difficulty"), None), it.get("no"))
              for it in items if it.get("target_level") in rank]
    graded = [g for g in graded if g[1] is not None]
    for a in graded:
        for b in graded:
            if rank[a[0]] > rank[b[0]] and a[1] < b[1]:
                err(f"{name}: R7 수준 역전 — {a[0]}({a[2]}번, {'쉬움보통어려움'[a[1]*2:a[1]*2+2]}) 이 "
                    f"{b[0]}({b[2]}번) 보다 쉽게 설정되었습니다.")

    levels_used = {it.get("target_level") for it in items}
    absent = [lv for lv in LEVELS[:want] if lv not in levels_used]
    if absent:
        warn(f"{name}: 표적 성취수준 {', '.join(absent)} 를 겨냥한 문항이 없습니다. "
             "모든 성취수준이 고르게 점검되는지 확인하세요.")


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    ap = argparse.ArgumentParser(description="스킬 간 인계 파일을 검증한다")
    ap.add_argument("--plan", action="store_true", help=".work/plan/ 만")
    ap.add_argument("--items", action="store_true", help=".work/items/ 만")
    args = ap.parse_args()
    do_plan = args.plan or not args.items
    do_items = args.items or not args.plan

    conf = load_conf()
    standards = load_standards()
    checked = 0

    if do_plan:
        files = sorted(PLAN_DIR.glob("*.json")) if PLAN_DIR.is_dir() else []
        if not files:
            warn(".work/plan/ 에 인계 파일이 없습니다. asa-guide 가 남겼는지 확인하세요.")
        for p in files:
            check_plan(p, conf, standards)
            checked += 1

    if do_items:
        files = sorted(ITEMS_DIR.glob("*.json")) if ITEMS_DIR.is_dir() else []
        for p in files:
            check_items(p, conf, standards)
            checked += 1

    print(f"인계 파일 검증 — {checked}개")
    print("-" * 60)
    for w in warnings:
        print(f"  [경고] {w}")
    for e in errors:
        print(f"  [오류] {e}")
    if not warnings and not errors:
        print("  이상 없음.")
    print("-" * 60)
    print(f"오류 {len(errors)}건, 경고 {len(warnings)}건")

    if errors:
        print("\n★ 오류가 있으면 작업이 끝난 것이 아닙니다. 고치고 다시 실행하세요.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
