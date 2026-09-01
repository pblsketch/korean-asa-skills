#!/usr/bin/env python3
"""
교과 팩 초기화 (Subject Pack Initializer)

다른 교과로 포크한 뒤 subject/ 를 템플릿 상태로 갈아끼운다.

    python scripts/init_subject.py --id math --name "수학과"
    python scripts/init_subject.py --id math --name "수학과" --en "Mathematics"

기존 subject/ 는 subject.bak-<타임스탬프> 로 백업된다.
FORKING.md 참조.
"""
from __future__ import annotations

import argparse
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE_DIR = ROOT / "subject-template"
SUBJECT_DIR = ROOT / "subject"


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    ap = argparse.ArgumentParser(description="교과 팩 초기화")
    ap.add_argument("--id", required=True, help="교과 id (영문 소문자, 예: math)")
    ap.add_argument("--name", required=True, help="교과 한글명 (예: 수학과)")
    ap.add_argument("--en", default="", help="교과 영문명 (선택)")
    ap.add_argument("--force", action="store_true", help="백업 없이 덮어쓰기")
    args = ap.parse_args()

    if not re.fullmatch(r"[a-z][a-z0-9_]*", args.id):
        print(f"오류: --id 는 영문 소문자로 시작하는 식별자여야 합니다 (받은 값: {args.id})")
        return 1

    if not TEMPLATE_DIR.is_dir():
        print(f"오류: 템플릿이 없습니다 — {TEMPLATE_DIR}")
        return 1

    # 기존 팩 백업
    if SUBJECT_DIR.exists():
        if args.force:
            shutil.rmtree(SUBJECT_DIR)
            print("기존 subject/ 를 삭제했습니다 (--force).")
        else:
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            backup = ROOT / f"subject.bak-{stamp}"
            shutil.move(str(SUBJECT_DIR), str(backup))
            print(f"기존 subject/ 를 백업했습니다 → {backup.name}")

    shutil.copytree(TEMPLATE_DIR, SUBJECT_DIR)
    (SUBJECT_DIR / "data" / "standards").mkdir(parents=True, exist_ok=True)
    (SUBJECT_DIR / "data" / "exemplars").mkdir(parents=True, exist_ok=True)
    for sub in ("standards", "exemplars"):
        (SUBJECT_DIR / "data" / sub / ".gitkeep").touch()

    # 알 수 있는 값만 치환한다. 나머지 TODO 는 사람이 채운다.
    manifest = SUBJECT_DIR / "subject.yaml"
    text = manifest.read_text(encoding="utf-8")
    text = text.replace("  id: TODO                 #", f"  id: {args.id}{' ' * max(1, 18 - len(args.id))}#", 1)
    text = text.replace("  name_ko: TODO            #", f"  name_ko: {args.name}{' ' * max(1, 13 - len(args.name))}#", 1)
    if args.en:
        text = text.replace("  name_en: TODO", f"  name_en: {args.en}", 1)
    manifest.write_text(text, encoding="utf-8")

    # 교과 특수 문서의 제목 자리 치환
    for name in ("difficulty-levers.md", "item-conventions.md", "misconceptions.md"):
        path = SUBJECT_DIR / name
        path.write_text(
            path.read_text(encoding="utf-8").replace("[교과명]", args.name),
            encoding="utf-8",
        )

    todo_count = sum(
        p.read_text(encoding="utf-8").count("TODO")
        for p in SUBJECT_DIR.rglob("*.*")
        if p.suffix in {".md", ".yaml"}
    )

    print(f"\nsubject/ 를 '{args.name}' 템플릿으로 초기화했습니다.")
    print("─" * 60)
    print("다음 순서로 채우세요 (FORKING.md 참조)\n")
    print("  1. subject/subject.yaml        — 코드 체계 · 과목 목록 · 시도 지침 · 원자료")
    print("  2. subject/difficulty-levers.md — ★ 가장 중요. §5 도출 절차를 따를 것")
    print("  3. subject/item-conventions.md")
    print("  4. subject/misconceptions.md")
    print(f"\n남은 TODO: {todo_count}곳\n")
    print("  python scripts/build_refs.py        # subject/data/ 생성")
    print("  python scripts/validate_subject.py  # 적합성 검사")
    print("─" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
