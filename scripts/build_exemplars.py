#!/usr/bin/env python3
"""
예시 평가도구 색인 빌드 (Exemplar Index Builder)

교육부·한국교육과정평가원 성취수준 보급본(.hwp)의 '예시 평가 도구' 요약표를 읽어
subject/data/exemplars/kice_eval_tools.json 을 만든다.

    python scripts/build_exemplars.py
    python scripts/build_exemplars.py --source kice_common
    python scripts/build_exemplars.py --keep-md

만드는 것은 **색인**이다. 문항 본문·지문·채점기준은 담지 않는다.
어느 성취기준에 어떤 유형의 국가 예시 평가도구가 있는지 찾아 주고, 실물은
사용자가 보급본에서 직접 보게 한다. (저작권 — NOTICE.md)

보급본은 과목별로 아래 형태의 요약표를 싣는다. 이 표만 읽는다.

    | 공통국어1-1 | 듣기·말하기 | [10공국1-01-01] | 단답형 | 평가 요소 … |
    | 화법과 언어-1 | -          | [12화언01-02]   | 선다형 | 평가 요소 … |

개별 평가도구 카드를 파싱하지 않는 이유는 카드 레이아웃이 유형마다 다르고
(선다형은 배점·정답 칸이 있고 수행평가는 없다) 표 병합이 많아 깨지기 쉽기 때문이다.
요약표는 과목마다 형태가 같다.

KICE 보급본은 전 교과 공통 양식이므로 이 파서는 교과 중립이다.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_refs import (  # noqa: E402  (같은 원자료·같은 변환을 쓴다)
    ROOT,
    SUBJECT_DIR,
    WORK_DIR,
    extract_markdown,
    norm,
)

OUT_DIR = SUBJECT_DIR / "data" / "exemplars"

# 평가 도구 유형 → 문항 갈래. 평가 방법 용어이므로 교과와 무관하다.
FAMILY = {
    "선다형": "선다형",
    "단답형": "서답형",
    "완성형": "서답형",
    "서술형": "서답형",
    "논술형": "서답형",
    "프로젝트": "수행평가",
    "포트폴리오": "수행평가",
    "구술·발표": "수행평가",
    "토의·토론": "수행평가",
    "실험·실습": "수행평가",
    "보고서": "수행평가",
}

# | 도구명-번호 | 영역 | [성취기준코드] | 유형 | 평가 요소 |
ROW_RE = re.compile(
    r"\|\s*(?P<ref>[^|]{2,40}?-\d+)\s*"
    r"\|\s*(?P<area>[^|]{0,24}?)\s*"
    r"\|\s*(?P<code>\[[^\]]+\])\s*"
    r"\|\s*(?P<type>[^|]{1,30}?)\s*"
    r"\|\s*(?P<element>[^|]{0,400}?)\s*\|"
)


def load_conf() -> dict:
    import yaml

    return yaml.safe_load((SUBJECT_DIR / "subject.yaml").read_text(encoding="utf-8"))


def split_types(raw: str) -> list[str]:
    """'토의·토론,포트폴리오' 처럼 한 칸에 둘 이상 적힌 경우를 가른다."""
    parts = [norm(p) for p in re.split(r"[,、/]", raw) if norm(p)]
    return parts or [norm(raw)]


def family_of(types: list[str]) -> str | None:
    fams = {FAMILY[t] for t in types if t in FAMILY}
    if not fams:
        return None
    # 한 도구에 갈래가 섞이면 수행평가로 본다 (수행 과제 안에 서답형이 들어가는 형태)
    return "수행평가" if "수행평가" in fams else fams.pop()


def build_area_lookup(courses: list[dict]) -> dict[str, dict[str, str]]:
    """과목별 {영역명: 영역코드}. 영역명은 subject.yaml 이 정본이다."""
    out: dict[str, dict[str, str]] = {}
    for c in courses:
        areas = c.get("areas") or {}
        out[c["id"]] = {norm(str(name)): str(code) for code, name in areas.items()}
    return out


def parse(markdown: str, code_rx: re.Pattern, token_to_course: dict[str, str],
          area_lookup: dict[str, dict[str, str]], source_id: str) -> tuple[list[dict], list[str]]:
    items: list[dict] = []
    warnings: list[str] = []
    seen: set[tuple[str, str]] = set()

    for m in ROW_RE.finditer(markdown):
        code = norm(m.group("code"))
        cm = code_rx.match(code)
        if not cm:
            continue                      # 성취기준 코드가 아니면 요약표 행이 아니다

        course_id = token_to_course.get(cm.group("course"))
        if course_id is None:
            warnings.append(f"{code}: subject.yaml 에 없는 과목 토큰 '{cm.group('course')}'")
            continue

        types = split_types(m.group("type"))
        family = family_of(types)
        if family is None:
            continue                      # 유형 칸이 아니면 요약표 행이 아니다

        ref = norm(m.group("ref"))
        key = (course_id, ref)
        if key in seen:                   # 보급본은 같은 표를 목차와 본문에 두 번 싣기도 한다
            continue
        seen.add(key)

        area_name = norm(m.group("area"))
        area_code = None
        if area_name and area_name != "-":
            area_code = area_lookup.get(course_id, {}).get(area_name)
            if area_code is None:
                warnings.append(f"{ref}: subject.yaml 의 areas 에 없는 영역명 '{area_name}'")
        else:
            area_name = None

        items.append({
            "ref": ref,
            "course_id": course_id,
            "code": code,
            "area": area_code,
            "area_name": area_name,
            "tool_types": types,
            "family": family,
            "element": norm(m.group("element")) or None,
            "source_id": source_id,
        })
    return items, warnings


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    ap = argparse.ArgumentParser(description="보급본의 예시 평가도구 요약표를 색인으로 만든다")
    ap.add_argument("--source", help="특정 sources.standards[].id 만 처리")
    ap.add_argument("--keep-md", action="store_true", help="중간 마크다운 보존")
    args = ap.parse_args()

    conf = load_conf()
    courses = conf.get("courses") or []
    token_to_course = {str(c["code_token"]): c["id"] for c in courses if c.get("code_token")}
    area_lookup = build_area_lookup(courses)

    pattern = ((conf.get("standard_code") or {}).get("pattern") or "").strip()
    if not pattern:
        sys.exit("subject.yaml 에 standard_code.pattern 이 없습니다.")
    code_rx = re.compile(pattern.replace("(?P<", "(?P<"))

    sources = [s for s in ((conf.get("sources") or {}).get("standards") or [])
               if "exemplar_items" in (s.get("contains") or [])]
    if args.source:
        sources = [s for s in sources if s.get("id") == args.source]
    if not sources:
        sys.exit("contains 에 exemplar_items 가 선언된 sources.standards 항목이 없습니다.")

    WORK_DIR.mkdir(exist_ok=True)
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    all_items: list[dict] = []
    all_warnings: list[str] = []

    for src in sources:
        primary = ROOT / str(src.get("primary", ""))
        if not primary.is_file():
            print(f"  [건너뜀] {src['id']}: 원자료가 없습니다 — {primary.name}")
            continue
        md_path = WORK_DIR / f"{src['id']}.md"
        markdown = extract_markdown(primary, md_path)
        items, warns = parse(markdown, code_rx, token_to_course, area_lookup, src["id"])
        print(f"  {src['id']:<16} {len(items):>4}건")
        all_items.extend(items)
        all_warnings.extend(warns)
        if not args.keep_md:
            md_path.unlink(missing_ok=True)

    if not all_items:
        sys.exit("색인을 만들지 못했습니다. 원자료와 요약표 형식을 확인하세요.")

    from collections import Counter
    by_course = Counter(i["course_id"] for i in all_items)
    by_family = Counter(i["family"] for i in all_items)

    payload = {
        "source": "kice",
        "kind": "exemplar_items",
        "kind_name": "국가 예시 평가도구 색인",
        "note": "색인만 담는다. 문항 본문·채점기준은 보급본 원본에서 확인할 것.",
        "built_at": datetime.now().isoformat(timespec="seconds"),
        "count": len(all_items),
        "by_course": dict(by_course),
        "by_family": dict(by_family),
        "items": sorted(all_items, key=lambda i: (i["course_id"], i["ref"])),
    }
    out = OUT_DIR / "kice_eval_tools.json"
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print("─" * 60)
    for fam, n in by_family.most_common():
        print(f"  {fam:<10} {n:>4}건")
    print("─" * 60)
    print(f"예시 평가도구 {len(all_items)}개 → {out.relative_to(ROOT)}")

    if all_warnings:
        print(f"\n경고 {len(all_warnings)}건")
        for w in dict.fromkeys(all_warnings):
            print(f"  · {w}")

    print("\n★ 원자료는 교육부·평가원 저작물이다. 저장소에 커밋하지 않는다 (.gitignore 적용됨).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
