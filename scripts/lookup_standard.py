#!/usr/bin/env python3
"""
성취수준 조회 (Standard Lookup)

subject/data/standards/ 에 빌드된 성취수준을 스킬이 바로 쓸 수 있는 형태로 꺼낸다.
asa-guide · asa-item · asa-analyze 가 공유한다.

    python scripts/lookup_standard.py "[10공국1-01-01]"
    python scripts/lookup_standard.py "[10공국1-01-01]" --with-area   # 영역별 성취수준 포함
    python scripts/lookup_standard.py --course gongguk1              # 과목 전체
    python scripts/lookup_standard.py --course gongguk1 --area 01
    python scripts/lookup_standard.py --search 대화의 원리
    python scripts/lookup_standard.py --list
    python scripts/lookup_standard.py "[10공국1-01-01]" --json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SUBJECT_DIR = ROOT / "subject"
DATA_DIR = SUBJECT_DIR / "data" / "standards"
LEVELS = ("A", "B", "C", "D", "E")


def load_conf() -> dict:
    try:
        import yaml
    except ImportError:
        sys.exit("PyYAML 이 필요합니다:  pip install pyyaml")
    path = SUBJECT_DIR / "subject.yaml"
    if not path.is_file():
        sys.exit(f"{path} 가 없습니다. 교과 팩이 설치되지 않았습니다.")
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def load_courses() -> dict[str, dict]:
    if not DATA_DIR.is_dir() or not any(DATA_DIR.glob("*.json")):
        sys.exit(
            "성취수준 데이터가 없습니다.\n"
            "  python scripts/build_refs.py  를 먼저 실행하세요."
        )
    return {
        p.stem: json.loads(p.read_text(encoding="utf-8"))
        for p in sorted(DATA_DIR.glob("*.json"))
    }


def load_plans() -> list[dict]:
    """`.work/plan/*.json` — asa-guide 가 남긴 인계 파일. 없으면 빈 목록."""
    d = ROOT / ".work" / "plan"
    out: list[dict] = []
    for path in sorted(d.glob("*.json")) if d.is_dir() else []:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        payload["_path"] = str(path.relative_to(ROOT))
        out.append(payload)
    return out


def plan_for(code: str, course_id: str, plans: list[dict]) -> dict | None:
    """이 성취기준을 편성한 인계 파일. 여럿이면 가장 최근 학기."""
    hits = [p for p in plans
            if p.get("course_id") == course_id and code in (p.get("standards") or [])]
    return max(hits, key=lambda p: str(p.get("semester", ""))) if hits else None


def fmt_plan(code: str, area_name: str | None, plan: dict | None) -> list[str]:
    """인계 정보 절. 인계 파일이 아예 없으면 아무것도 붙이지 않는다."""
    if plan is None:
        return []

    out = ["", f"### 학기 평가계획 — {plan.get('semester', '?')}  `{plan['_path']}`"]

    elements = (plan.get("elements") or {}).get(code)
    if elements:
        out += ["", "**평가 요소** (재도출하지 말고 그대로 쓸 것)", ""]
        out += [f"- {e}" for e in elements]

    # 최소 능력의 수행 특성 — 영역명 또는 성취기준 코드로 저장된다
    minlv = plan.get("min_level") or {}
    mine = minlv.get(code) or (minlv.get(area_name) if area_name else None)
    if mine:
        out += ["", "**최소 능력의 수행 특성** (Target PLD — 40% 지점)", ""]
        out += [f"- {m}" for m in mine]

    levels = plan.get("semester_levels") or {}
    if levels:
        out += ["", "**학기 단위 성취수준**", ""]
        for lv in LEVELS:
            entries = levels.get(lv) or []
            if not entries:
                continue
            mine_e = [e for e in entries if area_name and e.get("label") == area_name]
            others = [e for e in entries if e not in mine_e]
            if mine_e:
                out.append(f"- **{lv}** [{mine_e[0].get('label')}] {mine_e[0].get('text', '')}")
                rest = " · ".join(f"{e.get('label')}: {e.get('summary') or '(요약 없음)'}"
                                  for e in others)
                if rest:
                    out.append(f"  - 다른 영역 — {rest}")
            else:
                # 이 성취기준의 영역이 라벨에 없다 (3범주·역량 프레임 등) → 전부 요약으로
                rest = " · ".join(f"{e.get('label')}: {e.get('summary') or e.get('text', '')[:60]}"
                                  for e in entries)
                out.append(f"- **{lv}** {rest}")

        out += ["", "> 해당 라벨은 전문, 나머지는 요약입니다. 채점기준의 수행 수준을 이 진술과 연계하세요."]

    plan_ratio = (plan.get("assessment_plan") or {}).get("서논술형_반영비율", "MISSING")
    if plan_ratio is None:
        out += ["", "> ⚠ 서·논술형 반영 비율이 비어 있습니다. 소속 시도 시행지침을 확인하세요."]

    return out


def load_exemplars() -> dict[str, list[dict]]:
    """성취기준 코드 → 국가 예시 평가도구 목록. 색인이 없으면 빈 dict."""
    path = SUBJECT_DIR / "data" / "exemplars" / "kice_eval_tools.json"
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    out: dict[str, list[dict]] = {}
    for item in payload.get("items", []):
        out.setdefault(item.get("code", ""), []).append(item)
    return out


def fmt_exemplars(code: str, index: dict[str, list[dict]]) -> list[str]:
    """국가 예시 평가도구 절. 색인 자체가 없으면 아무것도 붙이지 않는다."""
    if not index:
        return []
    hits = index.get(code) or []
    if not hits:
        return [
            "",
            "### 국가 예시 평가도구 — **없음**",
            "",
            "> 이 성취기준에는 보급본의 예시 평가도구가 없습니다. 새로 개발해야 합니다.",
        ]
    out = [
        "",
        f"### 국가 예시 평가도구 {len(hits)}건",
        "",
        "| 번호 | 갈래 | 유형 | 평가 요소 |",
        "|---|---|---|---|",
    ]
    for h in hits:
        types = "·".join(h.get("tool_types") or [])
        out.append(f"| {h['ref']} | **{h['family']}** | {types} | {h.get('element') or '-'} |")
    out += ["", "> 색인만 담고 있습니다. **문항 본문과 채점기준은 보급본 원본**에서 확인하세요."]
    return out


def fmt_standard(std: dict, course: dict, conf: dict, with_area: bool, doc: dict,
                 exemplars: dict[str, list[dict]] | None = None,
                 plans: list[dict] | None = None) -> str:
    meta = next((c for c in conf["courses"] if c["id"] == course["course_id"]), {})
    area_label = f" · {std['area_name']}" if std.get("area_name") else ""

    out = [
        f"## {std['code']}",
        "",
        f"**과목** {course['course_name']} ({meta.get('type', '?')})"
        f"  |  **영역** {std['area']}{area_label}"
        f"  |  **평정** {meta.get('grading_scale', '?')}단계",
        "",
        f"**성취기준** {std['text']}",
        "",
        "### 성취기준별 성취수준",
        "",
        "| 수준 | 진술문 |",
        "|---|---|",
    ]
    for lv in LEVELS:
        if lv in std["levels"]:
            out.append(f"| **{lv}** | {std['levels'][lv]} |")

    if with_area:
        # area_levels 가 빈 목록인 과목(대개 선택과목)에서도 반드시 안내가 나가야 한다.
        # 이 안내가 '학기 단위 성취수준을 직접 종합하라'는 경로를 트리거하는 신호다.
        area = next(
            (a for a in (doc.get("area_levels") or []) if a.get("area") == std["area"]),
            None,
        )
        if area:
            out += [
                "",
                f"### 영역별 성취수준 — {area.get('area_name') or std['area']}",
                "",
                "| 수준 | 범주 | 진술문 |",
                "|---|---|---|",
            ]
            for lv in LEVELS:
                for cat, text in (area["levels"].get(lv) or {}).items():
                    out.append(f"| {lv} | {cat} | {text} |")
        else:
            out += [
                "",
                "### 영역별 성취수준 — **없음**",
                "",
                "> 이 과목에는 영역별 성취수준이 개발되어 있지 않습니다.",
                "> 기준은 과목 유형(공통/선택)이 아니라 **내용 영역 구분의 유무**입니다.",
                "> 영역이 구분되지 않는 과목은 영역 단위 자체가 없습니다.",
                ">",
                "> **학기 단위 성취수준은 성취기준별 성취수준에서 직접 종합해야 합니다.**",
                "> 없는 영역별 성취수준을 지어내지 마세요. (`core/level-writing.md` §1)",
            ]

    out += fmt_plan(std["code"], std.get("area_name"),
                    plan_for(std["code"], course["course_id"], plans or []))
    out += fmt_exemplars(std["code"], exemplars or {})
    return "\n".join(out)


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    ap = argparse.ArgumentParser(description="성취수준 조회")
    ap.add_argument("code", nargs="?", help="성취기준 코드 (예: [10공국1-01-01])")
    ap.add_argument("--course", help="과목 id")
    ap.add_argument("--area", help="영역 번호 (예: 01)")
    ap.add_argument("--search", nargs="+", help="성취기준 텍스트 검색")
    ap.add_argument("--list", action="store_true", help="과목 목록")
    ap.add_argument("--with-area", action="store_true", help="영역별 성취수준 함께 출력")
    ap.add_argument("--json", action="store_true", help="JSON 출력")
    args = ap.parse_args()

    conf = load_conf()
    docs = load_courses()

    # ── 과목 목록 ────────────────────────────────────────────────────
    if args.list:
        print(f"# {conf['subject']['name_ko']} — 과목 {len(docs)}개\n")
        print("| id | 과목 | 유형 | 성취기준 | 평정 | 영역별 성취수준 |")
        print("|---|---|---|---|---|---|")
        for cid, d in docs.items():
            m = next((c for c in conf["courses"] if c["id"] == cid), {})
            has = "있음" if d.get("area_levels") else "없음"
            print(
                f"| `{cid}` | {d['course_name']} | {m.get('type','?')} | "
                f"{len(d['standards'])} | {m.get('grading_scale','?')}단계 | {has} |"
            )
        return 0

    # ── 대상 선별 ────────────────────────────────────────────────────
    picked: list[tuple[dict, dict]] = []   # (doc, std)
    if args.code:
        code = args.code if args.code.startswith("[") else f"[{args.code}]"
        for d in docs.values():
            for s in d["standards"]:
                if s["code"] == code:
                    picked.append((d, s))
        if not picked:
            print(f"'{code}' 를 찾을 수 없습니다. --list 로 과목을 확인하세요.", file=sys.stderr)
            return 1
    elif args.course:
        d = docs.get(args.course)
        if d is None:
            print(f"과목 id '{args.course}' 가 없습니다. --list 로 확인하세요.", file=sys.stderr)
            return 1
        for s in d["standards"]:
            if args.area and s["area"] != args.area:
                continue
            picked.append((d, s))
    elif args.search:
        needle = " ".join(args.search)
        for d in docs.values():
            for s in d["standards"]:
                haystack = s["text"] + " " + " ".join(s["levels"].values())
                if needle in haystack:
                    picked.append((d, s))
        if not picked:
            print(f"'{needle}' 검색 결과가 없습니다.", file=sys.stderr)
            return 1
    else:
        ap.print_help()
        return 2

    # ── 출력 ────────────────────────────────────────────────────────
    exemplars = load_exemplars()
    plans = load_plans()

    if args.json:
        payload = []
        for d, s in picked:
            item = dict(s)
            item["course_id"] = d["course_id"]
            item["course_name"] = d["course_name"]
            if args.with_area:
                item["area_levels"] = next(
                    (a for a in d.get("area_levels", []) if a.get("area") == s["area"]),
                    None,
                )
            item["exemplars"] = exemplars.get(s["code"], [])
            item["plan"] = plan_for(s["code"], d["course_id"], plans)
            payload.append(item)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    for i, (d, s) in enumerate(picked):
        if i:
            print("\n---\n")
        print(fmt_standard(s, d, conf, args.with_area, d, exemplars, plans))
    if len(picked) > 1:
        print(f"\n> 성취기준 {len(picked)}개")
    return 0


if __name__ == "__main__":
    sys.exit(main())
