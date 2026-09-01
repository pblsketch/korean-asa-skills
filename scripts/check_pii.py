#!/usr/bin/env python3
"""
학생 개인정보 사전 점검 (PII Check)

이 도구에 넣기 전에, 자료에 학생 개인식별 정보가 남아 있는지 기계적으로 검사한다.

    python scripts/check_pii.py 성적자료.csv
    python scripts/check_pii.py 답안.txt --show      # 걸린 값도 함께 보기
    python scripts/check_pii.py *.csv

교육부·교육청 공동 「수행평가 시 AI 활용 관리 방안」이 열거한 개인식별 정보
(이름·학번·생년월일·주소·연락처·가족관계)를 기준으로 삼는다.

★ 통과했다고 안전이 보장되지 않는다.
  "3학년 2반 유일한 전학생" 처럼 조합하면 특정되는 간접 식별은
  기계가 잡지 못한다. 사람이 판단해야 한다.  → core/privacy.md
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
from pathlib import Path

# 개인식별 정보가 들어가는 열 이름
RISKY_COLUMNS = {
    "이름": "이름", "성명": "이름", "성 명": "이름", "학생명": "이름", "성함": "이름",
    "학번": "학번", "학생번호": "학번", "번호": "번호(반·번호일 수 있음)",
    "생년월일": "생년월일", "생일": "생년월일", "주민등록번호": "주민등록번호", "주민번호": "주민등록번호",
    "주소": "주소", "거주지": "주소",
    "연락처": "연락처", "전화": "연락처", "전화번호": "연락처", "휴대폰": "연락처",
    "핸드폰": "연락처", "이메일": "이메일", "메일": "이메일",
    "보호자": "가족관계", "학부모": "가족관계", "가족": "가족관계", "부모": "가족관계",
}

# 값에서 찾는 패턴
PATTERNS = [
    ("주민등록번호", re.compile(r"\b\d{6}\s*[-–]\s*[1-4]\d{6}\b")),
    ("전화번호", re.compile(r"\b01[016-9][-\s.]?\d{3,4}[-\s.]?\d{4}\b")),
    ("일반전화", re.compile(r"\b0\d{1,2}[-\s.]\d{3,4}[-\s.]\d{4}\b")),
    ("이메일", re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.]+\b")),
    ("생년월일", re.compile(r"\b(19|20)\d{2}\s*[-./년]\s*\d{1,2}\s*[-./월]\s*\d{1,2}\s*일?\b")),
    ("학번(8자리)", re.compile(r"\b(19|20)\d{6}\b")),
]

# 학년-반-번호 조합
CLASS_NO = re.compile(r"\b[1-3]\s*[-/]\s*\d{1,2}\s*[-/]\s*\d{1,2}\b")

MASK = re.compile(r"[가-힣]")


def mask(value: str) -> str:
    """값을 그대로 노출하지 않는다. 첫 글자만 남긴다."""
    v = value.strip()
    if len(v) <= 1:
        return "*"
    return v[0] + "*" * (len(v) - 1)


def scan_text(lines: list[str], show: bool) -> list[tuple[int, str, str]]:
    """줄마다 패턴을 찾되, 같은 구간에 여러 패턴이 걸리면 하나만 남긴다.

    (예: 010-1234-5678 은 '전화번호' 와 '일반전화' 에 모두 걸린다)
    """
    hits: list[tuple[int, str, str]] = []
    rules = PATTERNS + [("학년-반-번호 조합", CLASS_NO)]

    for i, line in enumerate(lines, 1):
        claimed: list[tuple[int, int]] = []
        for label, rx in rules:
            for m in rx.finditer(line):
                s, e = m.span()
                if any(s < ce and cs < e for cs, ce in claimed):   # 구간 겹침
                    continue
                claimed.append((s, e))
                hits.append((i, label, m.group(0) if show else mask(m.group(0))))
    return hits


def scan_csv_header(path: Path) -> list[tuple[str, str]]:
    """열 이름으로 위험 열을 찾는다."""
    try:
        with path.open(encoding="utf-8-sig", newline="") as fh:
            header = next(csv.reader(fh), [])
    except (OSError, UnicodeDecodeError, StopIteration):
        return []
    found = []
    for col in header:
        key = col.strip().replace(" ", "")
        for risky, kind in RISKY_COLUMNS.items():
            if risky.replace(" ", "") == key:
                found.append((col.strip(), kind))
                break
    return found


def check(path: Path, show: bool) -> int:
    try:
        text = path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError):
        print(f"  읽을 수 없습니다: {path}")
        return 0

    lines = text.splitlines()
    columns = scan_csv_header(path) if path.suffix.lower() == ".csv" else []
    hits = scan_text(lines, show)

    if not columns and not hits:
        print(f"✔ {path.name} — 기계 검사에서 걸린 것 없음")
        return 0

    print(f"✘ {path.name}")
    if columns:
        print("   [열 이름]")
        for col, kind in columns:
            print(f"     · '{col}' → {kind}. 이 열을 삭제하세요.")
    if hits:
        print("   [값]")
        shown = hits[:12]
        for line_no, label, value in shown:
            print(f"     · {line_no}행  {label}: {value}")
        if len(hits) > len(shown):
            print(f"     · … 외 {len(hits) - len(shown)}건")
    print()
    return len(columns) + len(hits)


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    ap = argparse.ArgumentParser(description="학생 개인정보 사전 점검")
    ap.add_argument("files", nargs="+", help="검사할 파일")
    ap.add_argument("--show", action="store_true",
                    help="걸린 값을 가리지 않고 그대로 표시 (기본은 마스킹)")
    args = ap.parse_args()

    print("학생 개인정보 사전 점검\n" + "─" * 56)
    total = 0
    for name in args.files:
        p = Path(name)
        if p.is_file():
            total += check(p, args.show)
        else:
            print(f"  파일이 없습니다: {name}")

    print("─" * 56)
    if total:
        print(f"의심 항목 {total}건.\n")
        print("  개인식별 정보를 지운 뒤 넣으세요. 문항 분석만 하실 거라면")
        print("  학생 행 자체가 필요 없습니다 — 문항별 집계만 넘기면 됩니다.")
        print("  익명화 방법:  core/privacy.md §3")
    else:
        print("기계 검사에서 걸린 것이 없습니다.")

    print()
    print("★ 통과가 안전을 보장하지는 않습니다.")
    print("  '3학년 2반 유일한 전학생' 처럼 조합하면 특정되는 간접 식별,")
    print("  학생 글에 담긴 가족사·건강·진로 같은 내용은 기계가 잡지 못합니다.")
    print("  넣기 전에 한 번 더 눈으로 확인해 주세요.")
    return 1 if total else 0


if __name__ == "__main__":
    sys.exit(main())
