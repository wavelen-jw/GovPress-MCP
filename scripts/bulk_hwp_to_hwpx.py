"""
bulk_hwp_to_hwpx.py — 한/글 COM 자동화로 .hwp 파일을 .hwpx로 일괄 변환

Windows 전용. 한컴오피스 한/글이 설치된 PC(서버H)에서 실행.

사용 예:
    # 기본 실행
    python bulk_hwp_to_hwpx.py --input D:\\hwp_raw --output D:\\hwpx_out

    # WSL 경로 직접 접근 (서버H가 서버W의 WSL 경로를 마운트한 경우)
    python bulk_hwp_to_hwpx.py ^
        --input  "\\\\wsl.localhost\\Ubuntu\\home\\USER\\govpress-mcp\\data\\raw" ^
        --output "\\\\wsl.localhost\\Ubuntu\\home\\USER\\govpress-mcp\\data\\raw" ^
        --overwrite

    # 테스트 (10건만, 창 표시)
    python bulk_hwp_to_hwpx.py --input D:\\hwp_raw --output D:\\hwpx_out --limit 10 --visible
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Iterator

# ── Windows 전용 체크 ─────────────────────────────────────
if sys.platform != "win32":
    print(
        "[FATAL] 이 스크립트는 Windows에서만 실행 가능합니다.\n"
        "       한/글 COM 인터페이스(HWPFrame.HwpObject)가 필요합니다.",
        file=sys.stderr,
    )
    sys.exit(2)

try:
    import win32com.client
    import win32com.client.gencache
    import pywintypes
except ImportError:
    print(
        "[FATAL] pywin32가 설치되어 있지 않습니다.\n"
        "       pip install pywin32",
        file=sys.stderr,
    )
    sys.exit(2)

LOG = logging.getLogger("bulk_hwp_to_hwpx")

HWP_PROGID = "HWPFrame.HwpObject"
# SaveAs 포맷 문자열 — 한/글 버전에 따라 "HWPX" 또는 "HWP XML" 가능
# 실패 시 FALLBACK_FORMAT 순서로 시도
HWPX_FORMATS = ["HWPX", "HWP XML"]


# ── 데이터 클래스 ──────────────────────────────────────────
@dataclass
class Stats:
    success: int = 0
    skipped: int = 0
    failed: int = 0
    failures: list[dict] = field(default_factory=list)

    @property
    def total(self) -> int:
        return self.success + self.skipped + self.failed


# ── 파일 탐색 ─────────────────────────────────────────────
def iter_hwp_files(root: Path, limit: int | None) -> Iterator[Path]:
    """입력 폴더를 재귀 탐색하여 .hwp 파일(확장자 대소문자 무관) 반환."""
    count = 0
    for p in sorted(root.rglob("*")):
        if p.suffix.lower() == ".hwp" and p.is_file():
            yield p
            count += 1
            if limit is not None and count >= limit:
                return


def dest_path(src: Path, input_root: Path, output_root: Path) -> Path:
    """입력 파일의 상대경로를 출력 루트에 적용하고 확장자를 .hwpx로 변경."""
    rel = src.relative_to(input_root)
    return (output_root / rel).with_suffix(".hwpx")


# ── COM 초기화 ────────────────────────────────────────────
def init_hwp(visible: bool) -> object:
    """한/글 COM 객체 생성 및 초기 설정."""
    try:
        hwp = win32com.client.gencache.EnsureDispatch(HWP_PROGID)
    except Exception:
        LOG.warning("gencache.EnsureDispatch 실패 → 일반 Dispatch로 재시도")
        hwp = win32com.client.Dispatch(HWP_PROGID)

    # 파일 경로 보안 검사 모듈 등록
    # 이 모듈이 있으면 파일 열 때 보안 확인 대화상자가 뜨지 않음
    try:
        hwp.RegisterModule("FilePathCheckDLL", "FilePathCheckerModule")
    except Exception:
        LOG.warning(
            "FilePathCheckerModule 등록 실패 — 보안 대화상자가 나타날 수 있습니다.\n"
            "  한/글 설치 경로(예: C:\\HNCPath)가 환경변수에 등록돼 있는지 확인하세요."
        )

    if visible:
        try:
            hwp.XHwpWindows.Active_XHwpWindow.Visible = True
        except Exception:
            LOG.debug("창 표시 설정 실패 (무시)")

    return hwp


def quit_hwp(hwp: object) -> None:
    """COM 객체 안전 종료."""
    try:
        hwp.Quit()
    except Exception as exc:
        LOG.debug("hwp.Quit() 예외 (무시): %s", exc)


# ── 단일 파일 변환 ─────────────────────────────────────────
def convert_one(hwp: object, src: Path, dst: Path) -> None:
    """
    Open(HWP) → SaveAs(HWPX) → Clear 흐름으로 단일 파일 변환.

    SaveAs 포맷 문자열은 한/글 버전에 따라 다를 수 있으므로
    HWPX_FORMATS 순서로 시도한다.
    """
    src_str = str(src.resolve())
    dst_str = str(dst.resolve())

    # 파일 열기
    hwp.Open(src_str, "HWP", "")

    last_exc: Exception | None = None
    saved = False
    for fmt in HWPX_FORMATS:
        try:
            hwp.SaveAs(dst_str, fmt, "")
            saved = True
            break
        except Exception as exc:
            last_exc = exc
            LOG.debug("SaveAs(%s) 실패, 다음 포맷 시도: %s", fmt, exc)

    # 문서 닫기 (저장 여부와 무관)
    try:
        hwp.Clear(1)
    except Exception:
        pass

    if not saved:
        raise RuntimeError(
            f"HWPX 저장 실패 (시도한 포맷: {HWPX_FORMATS}). "
            f"마지막 오류: {last_exc}"
        )


def recover_hwp(hwp: object) -> None:
    """변환 실패 후 COM 상태 복구 시도."""
    for method in (lambda: hwp.Clear(1), lambda: hwp.Clear(0)):
        try:
            method()
            return
        except Exception:
            pass


# ── 메인 실행 ─────────────────────────────────────────────
def run(args: argparse.Namespace) -> int:
    input_root = Path(args.input).resolve()
    output_root = Path(args.output).resolve()
    log_path = Path(args.log).resolve()

    if not input_root.is_dir():
        LOG.error("입력 폴더가 존재하지 않습니다: %s", input_root)
        return 1

    output_root.mkdir(parents=True, exist_ok=True)

    # 파일 목록
    files = list(iter_hwp_files(input_root, args.limit))
    total = len(files)
    pad = len(str(total))

    if total == 0:
        LOG.info("변환할 .hwp 파일이 없습니다 (입력: %s)", input_root)
        return 0

    LOG.info("총 %d개 파일 처리 시작 (입력: %s)", total, input_root)
    LOG.info("출력 경로: %s", output_root)

    stats = Stats()
    hwp: object | None = None

    try:
        hwp = init_hwp(args.visible)
        t_start = time.monotonic()

        for idx, src in enumerate(files, 1):
            dst = dest_path(src, input_root, output_root)
            elapsed = time.monotonic() - t_start
            rate = idx / elapsed if elapsed > 0 else 0
            eta = (total - idx) / rate if rate > 0 else 0

            # 진행률 출력
            bar_done = int((idx / total) * 20)
            bar = "#" * bar_done + "." * (20 - bar_done)
            print(
                f"\r[{bar}] {idx:{pad}}/{total}  "
                f"ETA {int(eta//60):02d}:{int(eta%60):02d}  "
                f"{src.name[:45]:<45}",
                end="",
                flush=True,
            )

            # 건너뜀 판정
            if dst.exists() and not args.overwrite:
                stats.skipped += 1
                LOG.debug("SKIP: %s", src.name)
                continue

            dst.parent.mkdir(parents=True, exist_ok=True)

            try:
                convert_one(hwp, src, dst)
                stats.success += 1
                LOG.debug("OK: %s → %s", src.name, dst.name)
            except Exception as exc:
                stats.failed += 1
                entry = {
                    "ts": datetime.now().isoformat(),
                    "src": str(src),
                    "dst": str(dst),
                    "error": str(exc),
                }
                stats.failures.append(entry)
                LOG.warning("\nFAIL: %s\n  %s", src.name, exc)
                recover_hwp(hwp)

    finally:
        print()  # 진행률 줄 종료
        if hwp is not None:
            quit_hwp(hwp)

    # 실패 로그 저장
    if stats.failures:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(log_path, "w", encoding="utf-8") as f:
            for entry in stats.failures:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        LOG.info("실패 로그 저장: %s (%d건)", log_path, len(stats.failures))

    # 요약
    total_time = time.monotonic() - (t_start if 'hwp' in dir() else 0)
    print(f"\n{'=' * 52}")
    print(f"  성공     : {stats.success:>6}")
    print(f"  건너뜀   : {stats.skipped:>6}")
    print(f"  실패     : {stats.failed:>6}")
    print(f"  합계     : {stats.total:>6}")
    print(f"{'=' * 52}")
    if stats.failed > 0:
        print(f"  실패 로그: {log_path}")
    print()

    return 0 if stats.failed == 0 else 1


# ── CLI ───────────────────────────────────────────────────
def main() -> int:
    parser = argparse.ArgumentParser(
        description="한/글 COM 자동화로 .hwp 파일을 .hwpx로 일괄 변환 (Windows 전용)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--input",    required=True,
                        help="입력 폴더 (재귀 탐색하여 .hwp 파일 수집)")
    parser.add_argument("--output",   required=True,
                        help="출력 폴더 (입력 폴더와 동일하면 .hwp 옆에 .hwpx 생성)")
    parser.add_argument("--overwrite", action="store_true",
                        help="이미 변환된 .hwpx 파일 덮어쓰기 (기본: 건너뜀)")
    parser.add_argument("--log",      default="hwp_convert_errors.jsonl",
                        help="실패 로그 경로 (JSONL, 기본: hwp_convert_errors.jsonl)")
    parser.add_argument("--limit",    type=int, default=None,
                        help="최대 처리 건수 — 테스트용 (기본: 무제한)")
    parser.add_argument("--visible",  action="store_true",
                        help="한/글 창 표시 (기본: 숨김 모드)")
    parser.add_argument("--log-level", default="INFO",
                        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
                        help="로그 레벨 (기본: INFO)")
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)-8s %(message)s",
        datefmt="%H:%M:%S",
    )
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
