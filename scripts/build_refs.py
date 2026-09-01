#!/usr/bin/env python3
"""
성취수준 레퍼런스 빌드 (Reference Builder)

교육부·한국교육과정평가원 성취수준 보급본(.hwp)에서 성취기준별 성취수준과
영역별 성취수준을 추출해 subject/data/standards/*.json 을 만든다.

    python scripts/build_refs.py
    python scripts/build_refs.py --source kice_common   # 특정 출처만
    python scripts/build_refs.py --keep-md              # 중간 마크다운 보존

전제
  - subject/subject.yaml 의 sources.standards 에 원자료가 선언되어 있어야 한다
  - 원자료 .hwp 가 저장소 루트에 있어야 한다 (저작권상 커밋하지 않음)
  - claw-hwp 플러그인이 설치되어 있어야 한다 (한컴오피스 불필요)

KICE 보급본은 전 교과 공통 양식이므로 이 파서는 교과 중립이다.
과목 식별은 성취기준 코드의 course 토큰으로 하며, subject.yaml 의
standard_code.pattern 을 그대로 사용한다.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SUBJECT_DIR = ROOT / "subject"
OUT_DIR = SUBJECT_DIR / "data" / "standards"
WORK_DIR = ROOT / ".work"

# KICE 보급본의 절 표지
SEC_STANDARD = "성취기준별 성취수준"
SEC_AREA_TITLE = "영역별 성취수준"
SEC_RE = re.compile(r"^\|\s*(\d+)\s*\|\s*([^|]+?)\s*\|")          # | 1 | 성취기준별 성취수준 |
SUBSEC_RE = re.compile(r"^\((\d+)\)\s*(.+?)\s*$")                  # (1) 듣기·말하기
LEVELS = ("A", "B", "C", "D", "E")
CATEGORIES = ("지식·이해", "과정·기능", "가치·태도")

# 옛한글 자모 → 현대 자모. 이것만 바꿔 주면 NFC 가 음절로 합성한다.
ARCHAIC_JAMO = str.maketrans({
    "ᅌ": "ᄋ",     # ᅌ 옛이응(초성) → ᄋ
    "ᇰ": "ᆼ",     # ᇰ 옛이응(종성) → ᆼ
})
# 합성되지 못하고 남은 한글 조합용 자모 (검증용)
STRAY_JAMO_RE = re.compile(r"[ᄀ-ᇿꥠ-꥿ힰ-퟿]")


def norm(text: str) -> str:
    """가운뎃점 변형·공백·옛한글 자모를 통일한다.

    보급본은 같은 진술문을 자리에 따라 다르게 조판한다.
      · 가운뎃점을 ･(U+FF65) / ・ / ∙ / ㆍ(U+318D 아래아) / · 로 섞어 씀
      · 가운뎃점 주변 공백이 있기도 없기도 함 ('개인적 ･ 사회적' vs '개인적･사회적')
    한국어 조판에서 가운뎃점은 공백 없이 쓰므로 공백을 제거해 정본을 만든다.

    조판에 옛이응(ᅌ) 같은 옛한글 자모가 섞이면 NFC 로도 합성되지 않아
    '있ᅌᅳᆷ을'(= 있음을) 처럼 자모가 그대로 노출된다. 현대 자모로 바꾼 뒤 합성한다.
    """
    for variant in ("･", "・", "∙", "‧", "ㆍ"):
        text = text.replace(variant, "·")
    text = unicodedata.normalize("NFC", text.translate(ARCHAIC_JAMO))
    text = text.replace("\xa0", " ")
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"\s*·\s*", "·", text)
    return text.strip()


def cells(line: str) -> list[str]:
    """마크다운 표 행을 셀 목록으로 자른다."""
    if not line.startswith("|"):
        return []
    parts = [norm(c) for c in line.strip().strip("|").split("|")]
    while parts and not parts[-1]:
        parts.pop()
    return parts


def find_claw_hwp() -> Path:
    base = Path.home() / ".claude" / "plugins" / "cache" / "claw-hwp" / "claw-hwp"
    candidates = sorted(base.glob("*/skills/hwp/scripts/extract_text.js"))
    if not candidates:
        sys.exit(
            "claw-hwp 플러그인을 찾을 수 없습니다.\n"
            "  claude plugin marketplace add https://github.com/DoHyun468/claw-hwp\n"
            "  claude plugin install claw-hwp@claw-hwp"
        )
    return candidates[-1]


def extract_markdown(src: Path, dest: Path) -> str:
    if not shutil.which("node"):
        sys.exit("node 를 찾을 수 없습니다. Node 18+ 가 필요합니다.")
    script = find_claw_hwp()
    dest.parent.mkdir(parents=True, exist_ok=True)
    with dest.open("w", encoding="utf-8") as fh:
        proc = subprocess.run(
            ["node", str(script), str(src), "--format", "markdown"],
            stdout=fh, stderr=subprocess.PIPE, text=True,
        )
    if proc.returncode != 0:
        sys.exit(f"HWP 추출 실패 ({src.name}):\n{proc.stderr[:500]}")
    return dest.read_text(encoding="utf-8")


def parse_document(lines: list[str], code_rx: re.Pattern) -> tuple[dict, dict, list[str]]:
    """문서 전체를 한 번 훑어 과목 토큰별로 성취수준을 모은다.

    절 표지('| 1 | 성취기준별 성취수준 |')로 구간을 자르지 않는다.
    보급본에 따라 절 표지와 내용의 순서가 뒤바뀐 경우가 있기 때문이다.
    (국어과 선택과목 보급본의 '독서와 작문'에서 실제로 발생)

    대신 성취기준 코드의 course 토큰으로 과목을 판별한다. 예시 평가 도구 카드에
    같은 표가 반복 등장하므로 코드 기준으로 중복을 제거하되, 내용이 다르면 보고한다.
    """
    lead = re.compile(r"^(\[[^\]]+\])\s*(.*)$")
    std_by_token: dict[str, dict[str, dict]] = {}
    area_by_token: dict[str, list[dict]] = {}
    conflicts: list[str] = []

    in_area = False
    area_name = ""
    cur_area: dict | None = None
    cur_std: dict | None = None
    cur_level = ""
    last_token: str | None = None

    for raw in lines:
        line = norm(raw)

        m = SEC_RE.match(line)
        if m and m.group(2) in (SEC_STANDARD, SEC_AREA_TITLE, "예시 평가 도구"):
            in_area = m.group(2) == SEC_AREA_TITLE
            cur_area, cur_std, cur_level = None, None, ""
            continue

        sub = SUBSEC_RE.match(line)
        if sub:
            area_name = sub.group(2)
            cur_std, cur_level = None, ""
            if in_area and last_token:
                cur_area = {"area": f"{int(sub.group(1)):02d}", "levels": {}}
                area_by_token.setdefault(last_token, []).append(cur_area)
            continue

        cs = cells(line)
        if not cs:
            continue

        # ── 영역별 성취수준 ─────────────────────────────────────────────
        if in_area and cur_area is not None:
            if cs[0] == area_name and len(cs) >= 4 and cs[1] in LEVELS and cs[2] in CATEGORIES:
                cur_level = cs[1]                                   # | 영역 | A | 지식·이해 | … |
                cur_area["levels"].setdefault(cur_level, {})[cs[2]] = cs[3]
            elif cs[0] in LEVELS and len(cs) >= 3 and cs[1] in CATEGORIES:
                cur_level = cs[0]                                   # | B | 지식·이해 | … |
                cur_area["levels"].setdefault(cur_level, {})[cs[1]] = cs[2]
            elif cs[0] in CATEGORIES and cur_level and len(cs) >= 2:
                cur_area["levels"].setdefault(cur_level, {})[cs[0]] = cs[1]  # | 과정·기능 | … |
            continue

        # ── 성취기준별 성취수준 ─────────────────────────────────────────
        m2 = lead.match(cs[0])
        if m2 and code_rx.match(m2.group(1)) and len(cs) >= 3 and cs[1] in LEVELS:
            code = m2.group(1)
            g = code_rx.match(code)
            token = g.group("course")
            last_token = token
            bucket = std_by_token.setdefault(token, {})

            if code in bucket:                       # 예시 평가 도구 카드의 반복 등장
                prev = bucket[code]["levels"].get(cs[1])
                if prev is not None and prev != cs[2]:
                    conflicts.append(f"{code} 수준 {cs[1]}: 문서 내 진술문 불일치")
                cur_std = None
                continue

            cur_std = {
                "code": code,
                "area": g.group("area"),
                "text": m2.group(2).strip(),
                "levels": {cs[1]: cs[2]},
            }
            bucket[code] = cur_std
        elif cur_std is not None and cs[0] in LEVELS and len(cs) >= 2:
            cur_std["levels"][cs[0]] = cs[1]

    standards = {tok: list(codes.values()) for tok, codes in std_by_token.items()}
    return standards, area_by_token, conflicts


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    ap = argparse.ArgumentParser(description="성취수준 레퍼런스 빌드")
    ap.add_argument("--source", help="특정 sources.standards[].id 만 처리")
    ap.add_argument("--keep-md", action="store_true", help="중간 마크다운을 .work/ 에 보존")
    args = ap.parse_args()

    try:
        import yaml
    except ImportError:
        sys.exit("PyYAML 이 필요합니다:  pip install pyyaml")

    manifest = SUBJECT_DIR / "subject.yaml"
    if not manifest.is_file():
        sys.exit(f"{manifest} 가 없습니다. 교과 팩이 설치되지 않았습니다.")
    conf = yaml.safe_load(manifest.read_text(encoding="utf-8"))

    code_rx = re.compile(conf["standard_code"]["pattern"])
    by_token = {c["code_token"]: c for c in conf["courses"]}
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    sources = (conf.get("sources") or {}).get("standards") or []
    if args.source:
        sources = [s for s in sources if s.get("id") == args.source]
        if not sources:
            sys.exit(f"sources.standards 에 id={args.source} 가 없습니다.")

    written: list[tuple[str, int, int]] = []
    problems: list[str] = []

    for src in sources:
        name = src.get("primary") or ""
        path = ROOT / name
        if not path.is_file():
            problems.append(f"{src['id']}: 원자료를 찾을 수 없습니다 — {name}")
            continue

        print(f"[{src['id']}] {name}")
        md_path = WORK_DIR / f"{src['id']}.md"
        text = extract_markdown(path, md_path)
        std_by_token, area_by_token, conflicts = parse_document(text.splitlines(), code_rx)
        problems.extend(f"{src['id']}: {c}" for c in conflicts)

        blocks: dict[str, dict] = {}
        for token, stds in std_by_token.items():
            course = by_token.get(token)
            if course is None:
                problems.append(f"{src['id']}: subject.yaml 에 없는 과목 토큰 — {token}")
                continue

            # 영역명은 문서에서 긁지 않고 subject.yaml 의 areas 계약에서 채운다.
            # 문서의 '(N) 제목' 표지는 예시 평가 도구 카드 제목과 구별되지 않아 신뢰할 수 없다.
            areas = course.get("areas") or {}
            for std in stds:
                std["area_name"] = areas.get(std["area"])
            area_levels = area_by_token.get(token, [])
            for area in area_levels:
                area["area_name"] = areas.get(area["area"])

            blocks[course["id"]] = {
                "course_id": course["id"],
                "course_name": course["name"],
                "code_token": token,
                "source": src["id"],
                "standards": stds,
                "area_levels": area_levels,
            }

        # 선언한 과목이 전부 나왔는가
        for course_id in src.get("covers") or []:
            if course_id not in blocks:
                course = next((c for c in conf["courses"] if c["id"] == course_id), None)
                label = course["name"] if course else course_id
                problems.append(
                    f"{src['id']}: '{label}' 의 성취기준을 하나도 찾지 못했습니다. "
                    "원자료 구조나 standard_code.pattern 을 확인하세요."
                )

        for course_id, payload in blocks.items():
            course = next(c for c in conf["courses"] if c["id"] == course_id)
            want = int(course["level_system"])

            # 무결성 점검
            for std in payload["standards"]:
                got = len(std["levels"])
                if got != want:
                    problems.append(
                        f"{course['name']} {std['code']}: 수준 {got}개 (기대 {want}개)"
                    )
            if course.get("has_area_levels") and not payload["area_levels"]:
                problems.append(
                    f"{course['name']}: has_area_levels=true 인데 영역별 성취수준을 찾지 못했습니다."
                )
            if not course.get("has_area_levels") and payload["area_levels"]:
                problems.append(
                    f"{course['name']}: has_area_levels=false 인데 영역별 성취수준이 추출됐습니다. "
                    "subject.yaml 을 확인하세요."
                )

            out_path = OUT_DIR / f"{course_id}.json"
            out_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            written.append(
                (course["name"], len(payload["standards"]), len(payload["area_levels"]))
            )

        if not args.keep_md:
            md_path.unlink(missing_ok=True)

    print("\n" + "─" * 60)
    print(f"{'과목':<16} {'성취기준':>8} {'영역별 성취수준':>16}")
    print("─" * 60)
    for course_name, n_std, n_area in written:
        print(f"{course_name:<16} {n_std:>8} {n_area:>16}")
    print("─" * 60)
    print(f"과목 {len(written)}개, 성취기준 {sum(n for _, n, _ in written)}개 → {OUT_DIR.relative_to(ROOT)}")

    if problems:
        print(f"\n확인이 필요한 항목 {len(problems)}건:")
        for p in problems:
            print(f"  · {p}")
        return 1

    print("\n이상 없음. `python scripts/validate_subject.py` 로 검증하세요.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
