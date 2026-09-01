#!/usr/bin/env python3
"""
KICE 학생평가지원포털(STAS) 평가도구 수집

https://stas.moe.go.kr 에서 이 교과 팩의 성취기준에 해당하는 평가도구를 찾아
subject/data/exemplars/ 에 색인한다.

    python scripts/stas_fetch.py                 # 색인만 (가볍다)
    python scripts/stas_fetch.py --detail        # 첨부 파일 목록까지
    python scripts/stas_fetch.py --kind DESCRPT_EVAL_TASK
    python scripts/stas_fetch.py --dry-run       # 로그인·건수만 확인

교과 중립 — 이 스크립트는 '국어'를 모른다.
subject/data/standards/ 의 성취기준 코드와 대조해 매칭되는 것만 가져오므로,
다른 교과로 포크해도 그대로 동작한다.

전제
  - .env 에 STAS_USER_ID / STAS_PASSWORD (본인 계정)
  - python scripts/build_refs.py 로 성취수준 데이터가 빌드되어 있을 것

★ 수집물은 교육부·한국교육과정평가원의 저작물이다. subject/data/ 는 .gitignore 되어 있다.
  저장소에 커밋하거나 재배포하지 않는다.
★ 첨부 파일 자동 다운로드는 지원하지 않는다. 포털이 저작권 동의를 받은 뒤에만
  파일을 내주며, 이 스크립트는 그 절차를 우회하지 않는다. 색인만 만든다.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
SUBJECT_DIR = ROOT / "subject"
STD_DIR = SUBJECT_DIR / "data" / "standards"
OUT_DIR = SUBJECT_DIR / "data" / "exemplars"

BASE = "https://stas.moe.go.kr"
LIST_API = "/rest/assmt/assmtEvalTask/assmtEvalTaskList"
DETAIL_API = "/rest/assmt/assmtEvalTask/assmtEvalTask"
FILE_API = "/cmn/file/file:dwld"

KINDS = {
    "DESCRPT_EVAL_TASK": "서·논술형 평가 도구",
    "ASSMT_EVAL_TASK": "수행평가 도구",
    "FLD_CNTR_EVAL_TASK": "현장중심 학생평가 도구",
}
SCHOOL_LEVEL = {"초등학교": "s1", "중학교": "s2", "고등학교": "s3"}
PAGE_SIZE = 100

# 목록에서 보존할 필드 (63개 중 의미 있는 것만)
KEEP = [
    "assmtEvalTaskSeq", "assmtEvalTaskClsCcd", "assmtEvalTaskNm",
    "eduCurclmNm", "eduCurclmCd", "schlClsNm", "schlClsCd",
    "grdGrpNm", "corsNm", "sbjtNm", "sbjtCd",
    "eduCurclmCorsSbjtNm", "corsSbjtClsfcA1Nm", "corsSbjtClsfcA3Nm",
    "acvmtStdCd", "acvmtStdNm", "acvmtStdSeq", "inqryCnt",
]


def load_env() -> dict[str, str]:
    env: dict[str, str] = {}
    path = ROOT / ".env"
    if not path.is_file():
        sys.exit(".env 가 없습니다. .env.example 을 복사해 계정을 채우세요.")
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
    if not env.get("STAS_USER_ID") or not env.get("STAS_PASSWORD"):
        sys.exit(".env 의 STAS_USER_ID / STAS_PASSWORD 가 비어 있습니다.")
    return env


def load_conf() -> dict:
    try:
        import yaml
    except ImportError:
        sys.exit("PyYAML 이 필요합니다:  pip install pyyaml")
    path = SUBJECT_DIR / "subject.yaml"
    if not path.is_file():
        sys.exit(f"{path} 가 없습니다.")
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def load_our_standards() -> dict[str, str]:
    """성취기준 코드 → 과목 id"""
    if not STD_DIR.is_dir() or not any(STD_DIR.glob("*.json")):
        sys.exit("성취수준 데이터가 없습니다.  python scripts/build_refs.py  를 먼저 실행하세요.")
    out: dict[str, str] = {}
    for p in STD_DIR.glob("*.json"):
        doc = json.loads(p.read_text(encoding="utf-8"))
        for st in doc["standards"]:
            out[st["code"]] = doc["course_id"]
    return out


def login(env: dict[str, str]) -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "User-Agent": "Mozilla/5.0 (compatible; asa-skills/0.1)",
        "X-Requested-With": "XMLHttpRequest",
    })
    s.get(f"{BASE}/mbr/mbr/login", timeout=20)
    r = s.get(f"{BASE}/rest/mbr/mbr/login",
              params={"sMbrId": env["STAS_USER_ID"], "sMbrPswd": env["STAS_PASSWORD"]},
              timeout=20)
    try:
        d = r.json()
    except ValueError:
        sys.exit("로그인 응답을 해석할 수 없습니다. 포털 구조가 바뀌었을 수 있습니다.")
    if not d.get("loginId"):
        sys.exit(f"로그인 실패: {d.get('message') or d}")
    print(f"로그인: {d.get('loginNm')} ({d.get('authId')})")
    return s


def fetch_kind(session, kind: str, curriculum: str, school: str,
               ours: dict[str, str], delay: float, dry: bool) -> list[dict]:
    params = {
        "page": 0, "size": PAGE_SIZE,
        "sAssmtEvalTaskClsCcd": kind,
        "sCorsSbjtClsCcd": "SBJT",
        "sCprtYn": "Y",
        "sEduCurclmCd": curriculum,
        "sSchlClsCd": school,
    }
    r = session.get(BASE + LIST_API, params=params, timeout=30)
    d = r.json()
    total, pages = d.get("totalElements", 0), d.get("totalPages", 0)
    print(f"\n[{kind}] {KINDS.get(kind, kind)} — 전체 {total}건 / {pages}쪽")
    if dry or total == 0:
        return []

    matched: list[dict] = []
    for page in range(pages):
        if page:
            time.sleep(delay)
            params["page"] = page
            d = session.get(BASE + LIST_API, params=params, timeout=30).json()
        for it in d.get("content", []):
            code = (it.get("acvmtStdCd") or "").strip()
            if code in ours:
                rec = {k: it.get(k) for k in KEEP if it.get(k) not in (None, "")}
                rec["course_id"] = ours[code]
                rec["acvmtStdCd"] = code
                matched.append(rec)
        print(f"  {page + 1}/{pages}쪽  누적 매칭 {len(matched)}건", end="\r")
    print(f"  {pages}/{pages}쪽  매칭 {len(matched)}건        ")
    return matched


def fetch_detail(session, items: list[dict], delay: float, download: bool) -> tuple[int, int]:
    """상세를 붙인다. 평가도구 본문은 PDF 첨부로 제공된다."""
    files_dir = OUT_DIR / "files"
    if download:
        files_dir.mkdir(parents=True, exist_ok=True)

    ok = saved = 0
    seen: dict[int, list] = {}          # 한 과제가 여러 성취기준에 걸리므로 재조회를 막는다
    for i, rec in enumerate(items, 1):
        seq = rec.get("assmtEvalTaskSeq")
        if not seq:
            continue
        if seq in seen:
            rec["files"] = seen[seq]
            continue
        time.sleep(delay)
        try:
            d = session.get(BASE + DETAIL_API,
                            params={"sAssmtEvalTaskSeq": seq}, timeout=30).json()
        except (requests.RequestException, ValueError):
            continue
        if not isinstance(d, dict):
            continue

        files = [
            {"fileSeq": f.get("fileSeq"), "fileKey": f.get("fileKey"),
             "fileNm": f.get("fileNm"), "fileExt": f.get("fileExt")}
            for f in (d.get("assmtEvalTaskFileList") or [])
            if f.get("fileKey")
        ]
        rec["files"] = files
        seen[seq] = files
        ok += 1

        print(f"  상세 {i}/{len(items)}  수집 {ok}", end="\r")
    print(f"  상세 {len(items)}/{len(items)}  수집 {ok}        ")
    return ok, saved


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    ap = argparse.ArgumentParser(description="STAS 평가도구 수집")
    ap.add_argument("--kind", choices=list(KINDS), help="한 종류만")
    ap.add_argument("--detail", action="store_true", help="첨부 파일 목록까지 수집")
    ap.add_argument("--files", action="store_true",
                    help="(사용 불가) 첨부 파일 자동 다운로드 — 포털의 저작권 동의 절차 때문에 지원하지 않는다")
    ap.add_argument("--dry-run", action="store_true", help="로그인·건수만 확인")
    args = ap.parse_args()

    if args.files:
        msg = [
            "첨부 파일 자동 다운로드는 지원하지 않습니다.",
            "",
            "  STAS 의 평가도구는 저작권 표시(sCprtYn=Y) 자료라, 포털이 파일을 내주기 전에",
            "  이용자에게 저작권 동의를 명시적으로 받습니다. 의도된 동의 절차이므로",
            "  스크립트가 대신 우회하지 않습니다.",
            "",
            "  파일이 필요하면 색인의 assmtEvalTaskSeq 로 포털에서 직접 내려받으세요.",
            "  https://stas.moe.go.kr  →  고등학교  →  서·논술형 평가 도구",
            "",
            "  색인(--detail)만으로도 어떤 성취기준에 어떤 평가도구가 있는지는 모두 확인됩니다.",
        ]
        for line in msg:
            print(line)
        return 2

    env = load_env()
    conf = load_conf()
    ours = load_our_standards()

    curriculum = str(conf["subject"].get("curriculum", "")).split()[0] or "2022"
    school = SCHOOL_LEVEL.get(conf["subject"].get("school_level", ""), "s3")
    delay = float(env.get("STAS_REQUEST_DELAY", 1.5))

    print(f"교과 팩: {conf['subject']['name_ko']} · 성취기준 {len(ours)}개")
    print(f"필터: 교육과정={curriculum} 학교급={school} · 요청 간격 {delay}s")

    session = login(env)
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    kinds = [args.kind] if args.kind else list(KINDS)
    summary: list[tuple[str, int]] = []

    for kind in kinds:
        items = fetch_kind(session, kind, curriculum, school, ours, delay, args.dry_run)
        if args.dry_run or not items:
            summary.append((kind, len(items)))
            continue
        if args.detail or args.files:
            fetch_detail(session, items, delay, args.files)

        by_course: dict[str, int] = {}
        for rec in items:
            by_course[rec["course_id"]] = by_course.get(rec["course_id"], 0) + 1

        out = OUT_DIR / f"stas_{kind.lower()}.json"
        out.write_text(json.dumps({
            "source": "stas", "kind": kind, "kind_name": KINDS[kind],
            "curriculum": curriculum, "school_level": school,
            "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "count": len(items), "by_course": by_course,
            "items": items,
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"  → {out.relative_to(ROOT)}")
        summary.append((kind, len(items)))

    print("\n" + "─" * 56)
    for kind, n in summary:
        print(f"  {KINDS[kind]:<22} {n:>5}건")
    print("─" * 56)
    if not args.dry_run:
        print("★ 수집물은 교육부·평가원 저작물이다. 저장소에 커밋하지 않는다 (.gitignore 적용됨).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
