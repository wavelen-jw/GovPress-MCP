# HWP → HWPX 일괄 변환 절차서

## 개요

21·22년도 정책브리핑 보도자료 중 HWP 구버전 파일은 `govpress-converter`로 직접 변환이
불가능하다. 한/글이 설치된 **서버H(Windows)** 에서 COM 자동화로 HWPX로 변환한 뒤,
**서버W(WSL)** 로 업로드해 기존 HWPX 파이프라인에 합류시킨다.

변환 우선순위: **HWPX 원본 > HWP → HWPX 변환 > PDF**

---

## 시스템 구성

| 역할 | 환경 | 위치 |
|---|---|---|
| 서버H | Windows + 한컴오피스 한/글 | COM 변환 실행 |
| 서버W | Windows 11 + WSL Ubuntu 24.04 | govpress-mcp 메인 파이프라인 |

---

## 설치 (서버H)

### 1. Python 및 pywin32 설치

```powershell
pip install pywin32
python -m pywin32_postinstall -install   # COM 등록 (관리자 권한 필요)
```

### 2. 스크립트 복사

```powershell
# govpress-mcp 레포에서
cd C:\path\to\govpress-mcp\scripts
# bulk_hwp_to_hwpx.py 가 이 폴더에 있음
```

### 3. 한/글 설치 확인

```powershell
python -c "import win32com.client; h = win32com.client.Dispatch('HWPFrame.HwpObject'); print('OK'); h.Quit()"
```

오류 없이 `OK`가 출력되면 정상.

---

## 실행 절차

### Step 1 — 서버W에서 HWP 파일 목록 추출

서버W WSL에서:

```bash
# M3 bulk_ingest 실행 중 hwp-queue.jsonl이 쌓임
# HWP 파일들은 data/raw/{yyyy}/{mm}/{news_item_id}.hwp 에 저장됨
find ~/govpress-mcp/data/raw -name "*.hwp" | wc -l

# hwp-queue.jsonl 건수 확인
wc -l ~/govpress-mcp/data/fetch-log/hwp-queue.jsonl
```

### Step 2 — 서버H에서 변환 실행

서버H가 서버W의 WSL 경로를 네트워크로 접근할 수 있는 경우 (추천):

```powershell
# 서버W의 WSL 경로를 직접 접근
python bulk_hwp_to_hwpx.py `
    --input  "\\SERVER_W\wsl$\Ubuntu\home\USER\govpress-mcp\data\raw" `
    --output "\\SERVER_W\wsl$\Ubuntu\home\USER\govpress-mcp\data\raw" `
    --log    "C:\temp\hwp_convert_errors.jsonl"
```

서버W WSL 경로를 직접 접근할 수 없는 경우 (로컬 경유):

```powershell
# 1. 서버W → 서버H 로 HWP 파일 복사 (scp 또는 공유 폴더)
scp -r USER@SERVER_W:/home/USER/govpress-mcp/data/raw/ C:\temp\hwp_raw\

# 2. 서버H에서 변환
python bulk_hwp_to_hwpx.py `
    --input  C:\temp\hwp_raw `
    --output C:\temp\hwpx_out `
    --log    C:\temp\hwp_convert_errors.jsonl

# 3. 결과 확인
python bulk_hwp_to_hwpx.py --input C:\temp\hwp_raw --output C:\temp\hwpx_out --limit 5 --visible
```

#### 테스트 실행 (10건, 창 표시)

```powershell
python bulk_hwp_to_hwpx.py `
    --input  C:\temp\hwp_raw `
    --output C:\temp\hwpx_out `
    --limit  10 `
    --visible
```

### Step 3 — 서버H → 서버W 업로드

변환된 `.hwpx` 파일을 서버W `data/raw/` 에 업로드한다.

```powershell
# 서버H PowerShell에서 rsync (WSL 통해 rsync 사용 가능)
# 또는 scp
scp -r C:\temp\hwpx_out\* USER@SERVER_W:/home/USER/govpress-mcp/data/raw/
```

WSL 네트워크 경로로 직접 복사하는 경우:

```powershell
robocopy C:\temp\hwpx_out "\\wsl.localhost\Ubuntu\home\USER\govpress-mcp\data\raw" `
    /E /XO /LOG:C:\temp\robocopy.log
```

### Step 4 — 서버W에서 재처리 (HWPX → MD)

```bash
# 서버W WSL에서
cd ~/projects/govpress-mcp

# hwp-queue.jsonl 기반으로 변환된 HWPX 재처리
python -m govpress_mcp.bulk_ingest \
    --from-hwp-queue data/fetch-log/hwp-queue.jsonl \
    --data-root ~/govpress-mcp/data

# 처리 결과 확인
cat data/fetch-log/hwp-reprocess-report.md
```

---

## 완료 기준

| 항목 | 기준 |
|---|---|
| HWPX 변환 성공률 | ≥ 90% (HWP 파일 중) |
| 변환 실패 로그 | `hwp_convert_errors.jsonl` 저장 완료 |
| MD 생성 | 변환 성공 건 전량 MD 생성 (source_format: hwpx) |
| data/raw/ 정리 | `.hwp` 파일은 변환 완료 후 보존 (삭제 금지 — 재변환 가능성) |

---

## 트러블슈팅

### "HWPFrame.HwpObject를 찾을 수 없습니다"

한/글이 설치되지 않았거나 COM 등록이 안 된 상태.

```powershell
# 한/글 재설치 후
python -m pywin32_postinstall -install
```

### 보안 확인 대화상자가 계속 뜸

`FilePathCheckerModule` 등록 실패. 한/글 설치 경로가 PATH에 있는지 확인:

```powershell
$env:Path -split ";" | Select-String "HNC"
# 결과 없으면 한/글 설치 경로(예: C:\Program Files\HNC\Hwp\) 수동 추가
```

### SaveAs("HWPX") 실패

한/글 버전에 따라 포맷 문자열이 다를 수 있음. 스크립트는 `"HWPX"` → `"HWP XML"` 순으로
자동 재시도. 둘 다 실패하면 `--visible` 모드로 실행해 수동 확인:

```powershell
python bulk_hwp_to_hwpx.py --input C:\test --output C:\test_out --limit 1 --visible
```

### 변환 중 한/글 멈춤 (행)

`--visible` 모드로 실행해 화면 확인. 반복 발생 시 해당 파일을 `--log` 로 수집 후
건너뛰기. 스크립트는 파일 하나 실패해도 전체 계속 진행함.

### 서버H → 서버W 업로드 속도 느림

HWP 파일은 평균 500KB~2MB. 5년치 hwp_legacy 비율 ~3%면 약 9,000건 × 1MB = ~9GB.
rsync 압축 옵션 사용:

```bash
rsync -avz --progress C:/temp/hwpx_out/ USER@SERVER_W:/home/USER/govpress-mcp/data/raw/
```

---

## 파일 구조 (변환 전후)

```
data/raw/
├── 2021/04/
│   ├── 123456789.hwp    ← M3에서 수집 (hwp_legacy)
│   └── 123456789.hwpx   ← M3.5에서 변환 생성
├── 2022/03/
│   ├── 987654321.hwp
│   └── 987654321.hwpx
└── fetch-log/
    ├── hwp-queue.jsonl       ← HWP 변환 대기 큐
    └── hwp-reprocess.jsonl   ← 재처리 결과
```

`.hwp` 원본은 삭제하지 않는다. `.hwpx` 생성 후 두 파일이 공존해도 됨.
