#!/usr/bin/env python3
"""
평가 결과 수치 분석 (Result Analyzer)

문항정보표 + 실제 응답 분포를 받아 결정적으로 계산할 수 있는 것을 전부 계산한다.
해석(오개념 추론·피드백)은 asa-analyze 스킬이 이 결과를 받아서 한다.

    python scripts/analyze_results.py results.csv
    python scripts/analyze_results.py results.csv --json
    python scripts/analyze_results.py --template > results.csv
    python scripts/analyze_results.py results.csv --dist "A:27,B:40,C:45,D:25,E:28,미도달:15" --common

입력 CSV (헤더 필수, 인코딩 UTF-8)
    문항,성취기준,점검성취수준,예상난이도,배점,정답,응답1,응답2,응답3,응답4,응답5,무응답
      · 점검성취수준 : A~E. 모르면 비워도 된다(수준 역전 검사만 생략)
      · 예상난이도   : 쉬움/보통/어려움. 비워도 된다(갭 검사만 생략)
      · 응답N        : 선지 N을 고른 인원 수
      · 무응답       : 선택 사항

★ 학생 실명·식별정보를 넣지 않는다. 문항 단위 집계만 받는다.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

LEVEL_ORDER = {"A": 0, "B": 1, "C": 2, "D": 3, "E": 4}
DIFF_ORDER = {"어려움": 0, "보통": 1, "쉬움": 2}
DEAD_OPTION_RATE = 5.0     # 이 미만이면 오답으로 기능하지 못함
GAP_FLAG_PP = 20.0         # 예상 구간 중앙값과 이만큼 벌어지면 플래그

TEMPLATE = """문항,성취기준,점검성취수준,예상난이도,배점,정답,응답1,응답2,응답3,응답4,응답5,무응답
1,[성취기준코드],A,어려움,4,5,81,1,12,23,63,0
2,[성취기준코드],B,보통,4,3,12,20,95,30,23,0
3,[성취기준코드],C,보통,4,4,9,14,25,120,12,0
4,[성취기준코드],D,쉬움,4,1,140,15,10,9,6,0
5,[성취기준코드],E,쉬움,3,2,8,155,7,6,4,0
"""


def difficulty_band(rate: float) -> str:
    if rate < 25:
        return "어려움"
    if rate < 75:
        return "보통"
    return "쉬움"


def band_center(label: str) -> float | None:
    return {"어려움": 12.5, "보통": 50.0, "쉬움": 87.5}.get(label)


def analyze(rows: list[dict]) -> dict:
    items: list[dict] = []
    problems: list[str] = []

    for r in rows:
        try:
            no = str(r["문항"]).strip()
            answer = int(str(r["정답"]).strip())
        except (KeyError, ValueError):
            problems.append(f"행을 읽을 수 없습니다: {r}")
            continue

        counts = {}
        for i in range(1, 6):
            raw = str(r.get(f"응답{i}", "") or "0").strip()
            counts[i] = int(raw) if raw.isdigit() else 0
        no_resp = str(r.get("무응답", "") or "0").strip()
        no_resp = int(no_resp) if no_resp.isdigit() else 0

        total = sum(counts.values()) + no_resp
        if total == 0:
            problems.append(f"{no}번: 응답 인원이 0입니다.")
            continue
        if answer not in counts:
            problems.append(f"{no}번: 정답 {answer} 가 선지 범위(1~5)를 벗어납니다.")
            continue

        rate = counts[answer] / total * 100
        actual = difficulty_band(rate)
        expected = (str(r.get("예상난이도", "") or "").strip() or None)
        level = (str(r.get("점검성취수준", "") or "").strip().upper() or None)

        dist = {i: counts[i] / total * 100 for i in counts}
        dead = [i for i, p in dist.items() if i != answer and p < DEAD_OPTION_RATE]
        distractors = sorted(
            ((i, p) for i, p in dist.items() if i != answer),
            key=lambda x: -x[1],
        )
        top_wrong, top_wrong_pct = distractors[0] if distractors else (None, 0.0)

        flags: list[str] = []
        if expected and expected != actual:
            center = band_center(expected)
            if center is not None and abs(rate - center) >= GAP_FLAG_PP:
                flags.append(f"예상 '{expected}' ↔ 실제 '{actual}' ({rate:.1f}%)")
        if dead:
            flags.append(f"변별도 저해 선지 {', '.join(f'{d}번' for d in dead)} (응답률 5% 미만)")
        if top_wrong_pct >= rate:
            flags.append(f"최다 응답이 오답 {top_wrong}번 ({top_wrong_pct:.1f}%) — 정답률({rate:.1f}%)보다 높음")
        if no_resp / total * 100 >= 10:
            flags.append(f"무응답 {no_resp / total * 100:.1f}% — 시간 부족 가능성")

        items.append({
            "문항": no,
            "성취기준": (r.get("성취기준") or "").strip(),
            "점검성취수준": level,
            "배점": (r.get("배점") or "").strip(),
            "정답": answer,
            "응시": total,
            "정답률": round(rate, 1),
            "예상난이도": expected,
            "실제난이도": actual,
            "답지반응": {str(i): round(p, 1) for i, p in dist.items()},
            "최다오답": top_wrong,
            "최다오답률": round(top_wrong_pct, 1),
            "사문항선지": dead,
            "플래그": flags,
        })

    # 수준 역전 — 상위 수준 문항이 하위 수준 문항보다 정답률이 높으면 안 된다
    leveled = [i for i in items if i["점검성취수준"] in LEVEL_ORDER]
    leveled.sort(key=lambda i: LEVEL_ORDER[i["점검성취수준"]])
    inversions = []
    for a, b in zip(leveled, leveled[1:]):
        if a["정답률"] > b["정답률"]:
            inversions.append(
                f"{a['점검성취수준']}({a['문항']}번 {a['정답률']}%) > "
                f"{b['점검성취수준']}({b['문항']}번 {b['정답률']}%)"
            )

    # 2/3 규칙 — 목표 수준 MCP의 약 66%가 맞히도록 개발했는지 사후 점검
    target_check = [
        {"문항": i["문항"], "수준": i["점검성취수준"], "정답률": i["정답률"],
         "이탈": round(i["정답률"] - 66.0, 1)}
        for i in leveled
    ]

    return {
        "문항수": len(items),
        "items": items,
        "수준역전": inversions,
        "목표정답률점검": target_check,
        "입력문제": problems,
    }


def parse_distribution(spec: str) -> dict[str, int]:
    """'A:27,B:40,C:45,D:25,E:28,미도달:15' → {'A':27, …}

    ★ 집계값만 받는다. 학생별 점수나 명단은 받지 않는다.
    미도달 인원 파악에는 집계로 충분하고, 명단은 교사가 나이스에서 본다.
    """
    out: dict[str, int] = {}
    for part in spec.split(","):
        if not part.strip():
            continue
        key, _, val = part.partition(":")
        key = key.strip()
        try:
            out[key] = int(val.strip())
        except ValueError:
            sys.exit(f"--dist 형식 오류: {part!r}  (예: A:27,B:40,…,미도달:15)")
    return out


def render_distribution(dist: dict[str, int], is_common: bool) -> str:
    """성취수준별 분포 → 최소 성취수준 보장지도 대상 규모."""
    total = sum(dist.values())
    if total == 0:
        return ""
    out = ["", "## 성취수준별 분포", "", "| 성취도 | 인원 | 비율 |", "|---|---|---|"]
    for k, v in dist.items():
        out.append(f"| {k} | {v}명 | {v / total * 100:.1f}% |")
    out.append(f"| **계** | **{total}명** | 100.0% |")

    under = dist.get("미도달", 0)
    e_cnt = dist.get("E", 0)

    out += ["", "### 최소 성취수준 대상", ""]
    if is_common:
        out += [
            f"- **미도달 {under}명 ({under / total * 100:.1f}%)** — 성취율 40% 미만."
            " 공통과목이므로 **최소 성취수준 보장지도 대상**이다 (`asa-guide` 작업 ④)",
            f"- E {e_cnt}명 ({e_cnt / total * 100:.1f}%) — 이수하였으나 최소 성취수준 구간."
            " 다음 학기 예방지도 후보로 볼 수 있다",
        ]
        if under == 0:
            out.append("- 미도달이 0명이면 **분할점수 산정이 느슨했는지** 함께 본다 (R2)")
    else:
        out += [
            "- **선택과목이므로 미도달 구분이 없다.** 2026학년도부터 학업 성취율 40% 기준이"
            " 적용되지 않아 성취율로는 미이수가 되지 않는다 (`core/asa-rules.md` §8)",
            f"- E {e_cnt}명 ({e_cnt / total * 100:.1f}%) — 성취율 60% 미만 구간",
            "- **출석률 2/3 미달자는 추가학습 대상**이다. 그 명단은 별도로 확인한다",
        ]
    out += [
        "",
        "> 이 분포는 **학기 합산 성취율** 기준일 때만 이수 판정에 쓸 수 있다.",
        "> 1차 지필 일부만으로 산출한 값이면 판정에 쓰지 말 것.",
        "> 개별 학생 명단은 나이스에서 확인한다 — 이 도구는 집계값만 다룬다.",
    ]
    return "\n".join(out)


def render(res: dict) -> str:
    out = ["# 평가 결과 수치 분석", ""]

    if res["입력문제"]:
        out += ["## ⚠ 입력 문제", ""]
        out += [f"- {p}" for p in res["입력문제"]] + [""]

    out += ["## 문항별 요약", "",
            "| 문항 | 수준 | 배점 | 정답 | 정답률 | 예상 | 실제 | 최다오답 |",
            "|---|---|---|---|---|---|---|---|"]
    for i in res["items"]:
        out.append(
            f"| {i['문항']} | {i['점검성취수준'] or '·'} | {i['배점'] or '·'} | {i['정답']} | "
            f"{i['정답률']}% | {i['예상난이도'] or '·'} | {i['실제난이도']} | "
            f"{i['최다오답'] or '·'}번 {i['최다오답률']}% |"
        )
    out.append("")

    flagged = [i for i in res["items"] if i["플래그"]]
    out += ["## 확인이 필요한 문항", ""]
    if flagged:
        for i in flagged:
            out.append(f"**{i['문항']}번** (목표 {i['점검성취수준'] or '?'}수준)")
            for f in i["플래그"]:
                out.append(f"  - {f}")
            dist = " · ".join(f"{k}번 {v}%" for k, v in i["답지반응"].items())
            out.append(f"  - 답지반응: {dist}")
            out.append("")
    else:
        out += ["플래그된 문항이 없습니다.", ""]

    out += ["## 수준 역전 (R7)", ""]
    if res["수준역전"]:
        out += ["상위 수준 문항이 하위 수준보다 쉬웠습니다. 분할점수 산출의 전제가 깨집니다.", ""]
        out += [f"- {x}" for x in res["수준역전"]] + [""]
    else:
        out += ["역전 없음.", ""]

    out += ["## 목표 정답률(약 66%) 대비", "",
            "> 선택형은 목표 수준 최소 능력자의 약 2/3가 맞히도록 개발한다.",
            "> 전체 응시자 기준 정답률이므로 참고치다. 큰 이탈은 난이도 추정 역량 보정의 단서가 된다.", "",
            "| 문항 | 수준 | 정답률 | 66% 대비 |", "|---|---|---|---|"]
    for t in res["목표정답률점검"]:
        sign = "+" if t["이탈"] > 0 else ""
        out.append(f"| {t['문항']} | {t['수준']} | {t['정답률']}% | {sign}{t['이탈']}%p |")
    out.append("")

    out += ["---", "",
            "다음은 해석 단계다. **오개념을 단정하기 전에 네 가지를 먼저 배제한다**",
            "(문항 결함 · 변별도 저해 선지 · 미학습 · 시험 운영 요인).",
            "`core/result-analysis.md` §4, `subject/misconceptions.md` 참조."]
    return "\n".join(out)


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    ap = argparse.ArgumentParser(description="평가 결과 수치 분석")
    ap.add_argument("csv", nargs="?", help="문항 단위 집계 CSV")
    ap.add_argument("--json", action="store_true", help="JSON 출력")
    ap.add_argument("--template", action="store_true", help="입력 CSV 서식 출력")
    ap.add_argument("--dist", metavar="SPEC",
                    help="성취수준별 분포(집계값만) — 예: A:27,B:40,C:45,D:25,E:28,미도달:15")
    ap.add_argument("--common", action="store_true",
                    help="공통과목이다 (성취율 40%% 이수 기준 적용). 없으면 선택과목으로 본다")
    ap.add_argument("--from-items", metavar="JSON",
                    help="asa-item 이 만든 .work/items/*.json 으로 CSV 뼈대 생성 "
                         "(응답 인원만 채우면 된다)")
    args = ap.parse_args()

    if args.template:
        print(TEMPLATE, end="")
        return 0

    if args.from_items:
        src = Path(args.from_items)
        if not src.is_file():
            print(f"파일이 없습니다: {src}", file=sys.stderr)
            return 1
        data = json.loads(src.read_text(encoding="utf-8"))
        code = data.get("code", "")
        out = [",".join(["문항", "성취기준", "점검성취수준", "예상난이도",
                         "배점", "정답", "응답1", "응답2", "응답3", "응답4", "응답5", "무응답"])]
        for it in data.get("items", []):
            out.append(",".join([
                str(it.get("no", "")), code,
                str(it.get("target_level", "") or ""),
                str(it.get("difficulty", "") or ""),
                str(it.get("points", "") or ""),
                str(it.get("answer", "") or ""),
                "", "", "", "", "", "",
            ]))
        print("\n".join(out))
        print("\n# ↑ 응답1~5 와 무응답 칸에 인원 수를 채운 뒤 이 파일로 분석하세요.",
              file=sys.stderr)
        return 0
    if not args.csv:
        ap.print_help()
        return 2

    path = Path(args.csv)
    if not path.is_file():
        print(f"파일이 없습니다: {path}", file=sys.stderr)
        return 1

    with path.open(encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.DictReader(fh))
    if not rows:
        print("데이터 행이 없습니다.", file=sys.stderr)
        return 1

    res = analyze(rows)
    dist = parse_distribution(args.dist) if args.dist else None
    if dist:
        res["distribution"] = dist

    if args.json:
        print(json.dumps(res, ensure_ascii=False, indent=2))
    else:
        print(render(res))
        if dist:
            print(render_distribution(dist, args.common))
    return 0


if __name__ == "__main__":
    sys.exit(main())
