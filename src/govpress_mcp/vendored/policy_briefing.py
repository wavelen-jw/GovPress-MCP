# Source: GovPress_PDF_MD@e614ecf6da43 server/app/adapters/policy_briefing.py
# Vendored on 2026-04-18. Do not edit without updating the SHA marker.

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from html import escape, unescape
import json
from pathlib import Path
import re
import subprocess
import tempfile
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET


PRESS_RELEASE_LIST_URL = "https://apis.data.go.kr/1371000/pressReleaseService/pressReleaseList"
REQUEST_USER_AGENT = "govpress-mcp-bulk/1.0 (+https://mcp.govpress.cloud)"
_APPENDIX_PREFIXES = ("붙임", "별첨", "첨부")
_PRESS_LABEL_RE = re.compile(r"^(보도자료|보도참고자료)\s*$")
_CATALOG_REFRESH_INTERVAL_SECONDS = 3600
_ATTACHMENT_HTML_PREFIXES = (b"<!doctype html", b"<html", b"<?xml")


def _normalize_policy_briefing_title(text: str) -> str:
    return re.sub(r"\s+", " ", unescape(text or "")).strip()


def _build_attachment_request_headers(item: "PolicyBriefingItem") -> dict[str, str]:
    headers = {
        "User-Agent": REQUEST_USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
        "Referer": item.original_url or "https://www.korea.kr/",
    }
    return headers


def _looks_like_html_error(content: bytes) -> bool:
    head = content[:256].lstrip().lower()
    if not head:
        return False
    return any(head.startswith(prefix) for prefix in _ATTACHMENT_HTML_PREFIXES)


@dataclass(frozen=True)
class PolicyBriefingAttachment:
    file_name: str
    file_url: str

    @property
    def extension(self) -> str:
        lower = self.file_name.lower()
        if "." not in lower:
            return ""
        return "." + lower.rsplit(".", 1)[-1]

    @property
    def is_hwpx(self) -> bool:
        return self.extension == ".hwpx"

    @property
    def is_pdf(self) -> bool:
        return self.extension == ".pdf"

    @property
    def is_appendix(self) -> bool:
        stripped = self.file_name.strip().lstrip("[").lstrip("<")
        return stripped.startswith(_APPENDIX_PREFIXES)


@dataclass(frozen=True)
class PolicyBriefingItem:
    news_item_id: str
    title: str
    department: str
    approve_date: str
    original_url: str
    attachments: tuple[PolicyBriefingAttachment, ...]

    @property
    def primary_hwpx(self) -> PolicyBriefingAttachment | None:
        hwpx_files = [attachment for attachment in self.attachments if attachment.is_hwpx]
        if not hwpx_files:
            return None
        primary = next((attachment for attachment in hwpx_files if not attachment.is_appendix), None)
        return primary or hwpx_files[0]

    @property
    def primary_pdf(self) -> PolicyBriefingAttachment | None:
        pdf_files = [attachment for attachment in self.attachments if attachment.is_pdf]
        if not pdf_files:
            return None
        primary = next((attachment for attachment in pdf_files if not attachment.is_appendix), None)
        return primary or pdf_files[0]


@dataclass(frozen=True)
class DownloadedPolicyBriefingFile:
    item: PolicyBriefingItem
    attachment: PolicyBriefingAttachment
    content: bytes

    @property
    def is_zip_container(self) -> bool:
        return self.content.startswith(b"PK\x03\x04")


@dataclass(frozen=True)
class PolicyBriefingCachedDocument:
    news_item_id: str
    file_name: str
    markdown_text: str
    markdown_html: str
    html_preview_text: str
    html_preview_html: str
    title: str | None
    department: str | None
    cached_at: str
    original_content: bytes | None = None


@dataclass(frozen=True)
class PolicyBriefingCatalogResult:
    items: list[PolicyBriefingItem]
    last_refreshed_at: str | None
    served_stale: bool = False
    stale_reason: str | None = None


class PolicyBriefingClient:
    def __init__(
        self,
        *,
        service_key: str | None,
        list_url: str = PRESS_RELEASE_LIST_URL,
        timeout_seconds: int = 8,
    ) -> None:
        self._service_key = (service_key or "").strip()
        self._list_url = list_url
        self._timeout_seconds = timeout_seconds

    @property
    def configured(self) -> bool:
        return bool(self._service_key)

    def list_items(self, target_date: date) -> list[PolicyBriefingItem]:
        if not self.configured:
            raise RuntimeError("정책브리핑 API 서비스키가 설정되지 않았습니다.")

        ymd = target_date.strftime("%Y%m%d")
        query = urllib.parse.urlencode(
            {
                "serviceKey": self._service_key,
                "startDate": ymd,
                "endDate": ymd,
            }
        )
        request = urllib.request.Request(
            f"{self._list_url}?{query}",
            headers={"User-Agent": REQUEST_USER_AGENT},
        )
        with urllib.request.urlopen(request, timeout=self._timeout_seconds) as response:
            payload = response.read()

        root = ET.fromstring(payload)
        result_code = (root.findtext("./header/resultCode") or "").strip()
        if result_code and result_code != "0":
            result_msg = (root.findtext("./header/resultMsg") or "API call failed").strip()
            raise RuntimeError(f"정책브리핑 API 호출 실패: {result_code} {result_msg}")

        items: list[PolicyBriefingItem] = []
        for node in root.findall("./body/NewsItem"):
            attachments = tuple(
                PolicyBriefingAttachment(file_name=file_name, file_url=file_url)
                for file_name, file_url in _extract_attachment_pairs(node)
                if file_name and file_url
            )
            items.append(
                PolicyBriefingItem(
                    news_item_id=(node.findtext("NewsItemId") or "").strip(),
                    title=_normalize_policy_briefing_title(node.findtext("Title") or ""),
                    department=unescape((node.findtext("MinisterCode") or "").strip()),
                    approve_date=(node.findtext("ApproveDate") or "").strip(),
                    original_url=(node.findtext("OriginalUrl") or "").strip(),
                    attachments=attachments,
                )
            )
        return items

    def list_today_hwpx_items(self, target_date: date) -> list[PolicyBriefingItem]:
        return [item for item in self.list_items(target_date) if item.primary_hwpx is not None]

    def download_primary_hwpx(self, news_item_id: str, *, target_date: date) -> DownloadedPolicyBriefingFile:
        items = self.list_today_hwpx_items(target_date)
        item = next((entry for entry in items if entry.news_item_id == news_item_id), None)
        if item is None:
            raise KeyError(news_item_id)
        return self.download_item_hwpx(item)

    def download_item_hwpx(self, item: PolicyBriefingItem) -> DownloadedPolicyBriefingFile:
        attachment = item.primary_hwpx
        if attachment is None:
            raise ValueError("HWPX 첨부파일이 없는 기사입니다.")

        return self.download_attachment(item, attachment)

    def download_attachment(
        self,
        item: PolicyBriefingItem,
        attachment: PolicyBriefingAttachment,
    ) -> DownloadedPolicyBriefingFile:
        if not attachment.file_url:
            raise ValueError("첨부파일 URL이 비어 있습니다.")

        headers = _build_attachment_request_headers(item)
        request = urllib.request.Request(
            attachment.file_url,
            headers=headers,
        )
        try:
            with urllib.request.urlopen(request, timeout=self._timeout_seconds) as response:
                content = response.read()
        except Exception:
            content = self._download_attachment_with_curl(attachment.file_url, headers=headers)
        if not content:
            raise ValueError("첨부파일 다운로드 결과가 비어 있습니다.")
        if _looks_like_html_error(content):
            raise ValueError("첨부파일 다운로드 결과가 실제 문서가 아니라 HTML 에러 페이지입니다.")
        return DownloadedPolicyBriefingFile(item=item, attachment=attachment, content=content)

    def _download_attachment_with_curl(self, file_url: str, *, headers: dict[str, str] | None = None) -> bytes:
        command = [
            "curl",
            "-L",
            "--fail",
            "--silent",
            "--show-error",
            "--max-time",
            str(self._timeout_seconds),
            file_url,
        ]
        header_values = dict(headers or {})
        user_agent = header_values.pop("User-Agent", "").strip()
        if user_agent:
            command.extend(["-A", user_agent])
        for key, value in header_values.items():
            if value.strip():
                command.extend(["-H", f"{key}: {value}"])
        result = subprocess.run(
            command,
            check=False,
            capture_output=True,
        )
        if result.returncode != 0:
            stderr = result.stderr.decode("utf-8", errors="replace").strip()
            raise RuntimeError(stderr or f"첨부파일 다운로드 실패: curl exit {result.returncode}")
        return result.stdout



class PolicyBriefingCatalog:
    def __init__(self, *, client: PolicyBriefingClient, cache_path: Path) -> None:
        self._client = client
        self._legacy_cache_path = cache_path
        self._cache_dir = cache_path.parent / "policy_briefing_catalog"
        self._cache_dir.mkdir(parents=True, exist_ok=True)

    def list_cached_items(self, *, target_date: date, ensure_fresh: bool = True) -> list[PolicyBriefingItem]:
        return self.list_cached_items_with_status(target_date=target_date, ensure_fresh=ensure_fresh).items

    def list_cached_items_with_status(
        self,
        *,
        target_date: date,
        ensure_fresh: bool = True,
    ) -> PolicyBriefingCatalogResult:
        self._migrate_legacy_store_if_needed()
        store = self._load_day_store(target_date)
        today = date.today()
        should_refresh = ensure_fresh and _should_refresh_catalog(store, target_date, today)
        served_stale = False
        stale_reason: str | None = None
        if should_refresh:
            try:
                fetched_items = self._client.list_items(target_date)
            except Exception as exc:
                if not store.get("items"):
                    raise
                served_stale = True
                stale_reason = str(exc).strip() or exc.__class__.__name__
            else:
                store = {"items": {item.news_item_id: _serialize_item(item) for item in fetched_items}}
                self._save_day_store(target_date, store)
        items = [
            item
            for payload in store["items"].values()
            for item in [_deserialize_item(payload)]
            if _matches_target_date(item, target_date)
        ]
        return PolicyBriefingCatalogResult(
            items=sorted(items, key=_item_sort_key, reverse=True),
            last_refreshed_at=(store.get("last_refreshed_at") or None) if isinstance(store, dict) else None,
            served_stale=served_stale,
            stale_reason=stale_reason,
        )

    def get_cached_item(self, news_item_id: str) -> PolicyBriefingItem | None:
        self._migrate_legacy_store_if_needed()
        for path in sorted(self._cache_dir.glob("*.json"), reverse=True):
            payload = self._load_store_file(path)["items"].get(news_item_id)
            if payload is not None:
                return _deserialize_item(payload)
        return None

    def refresh_today(self, target_date: date) -> list[PolicyBriefingItem]:
        return self.list_cached_items(target_date=target_date, ensure_fresh=True)

    def iter_cached_items(self) -> list[PolicyBriefingItem]:
        self._migrate_legacy_store_if_needed()
        items: list[PolicyBriefingItem] = []
        for path in sorted(self._cache_dir.glob("*.json"), reverse=True):
            store = self._load_store_file(path)
            for payload in store["items"].values():
                if isinstance(payload, dict):
                    items.append(_deserialize_item(payload))
        return items

    def _day_store_path(self, target_date: date) -> Path:
        return self._cache_dir / f"{target_date.isoformat()}.json"

    def _load_store_file(self, path: Path) -> dict[str, object]:
        if not path.exists():
            return {"last_refreshed_at": "", "items": {}}
        payload = json.loads(path.read_text())
        items = payload.get("items")
        if not isinstance(items, dict):
            items = {}
        last_refreshed_at = payload.get("last_refreshed_at")
        if not isinstance(last_refreshed_at, str):
            last_refreshed_at = ""
        return {"last_refreshed_at": last_refreshed_at, "items": items}

    def _load_day_store(self, target_date: date) -> dict[str, object]:
        return self._load_store_file(self._day_store_path(target_date))

    def _save_day_store(self, target_date: date, store: dict[str, object]) -> None:
        store_with_timestamp = {
            **store,
            "last_refreshed_at": datetime.now(UTC).isoformat(),
        }
        self._day_store_path(target_date).write_text(json.dumps(store_with_timestamp, ensure_ascii=False, indent=2))

    def _migrate_legacy_store_if_needed(self) -> None:
        if not self._legacy_cache_path.exists():
            return
        if any(self._cache_dir.glob("*.json")):
            return

        legacy_store = self._load_store_file(self._legacy_cache_path)
        grouped_items: dict[str, dict[str, object]] = {}
        for payload in legacy_store["items"].values():
            if not isinstance(payload, dict):
                continue
            item = _deserialize_item(payload)
            target_date = _approve_date_to_iso(item.approve_date)
            if target_date is None:
                continue
            grouped_items.setdefault(target_date, {})[item.news_item_id] = _serialize_item(item)

        for target_date, items in grouped_items.items():
            self._save_day_store(date.fromisoformat(target_date), {"items": items})


class PolicyBriefingCache:
    def __init__(self, *, client: PolicyBriefingClient, cache_dir: Path) -> None:
        self._client = client
        self._cache_dir = cache_dir
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        self._index_path = self._cache_dir / "index.json"
        self._originals_dir = self._cache_dir / "originals"
        self._originals_dir.mkdir(parents=True, exist_ok=True)

    def get(self, news_item_id: str) -> PolicyBriefingCachedDocument | None:
        payload = self._load_index().get(news_item_id)
        if not isinstance(payload, dict):
            return None
        file_name = str(payload.get("file_name", ""))
        return PolicyBriefingCachedDocument(
            news_item_id=news_item_id,
            file_name=file_name,
            markdown_text=str(payload.get("markdown_text", "")),
            markdown_html=str(payload.get("markdown_html", "")),
            html_preview_text=str(payload.get("html_preview_text", "")),
            html_preview_html=str(payload.get("html_preview_html", "")),
            title=str(payload.get("title")) if payload.get("title") is not None else None,
            department=str(payload.get("department")) if payload.get("department") is not None else None,
            cached_at=str(payload.get("cached_at", "")),
            original_content=self._load_original_content(news_item_id, file_name),
        )

    def save(
        self,
        *,
        item: PolicyBriefingItem,
        markdown_text: str,
        markdown_html: str,
        html_preview_text: str,
        html_preview_html: str,
        title: str | None,
        department: str | None,
        original_content: bytes,
        file_name: str | None = None,
    ) -> PolicyBriefingCachedDocument:
        cached = PolicyBriefingCachedDocument(
            news_item_id=item.news_item_id,
            file_name=file_name or (item.primary_hwpx.file_name if item.primary_hwpx else ""),
            markdown_text=markdown_text,
            markdown_html=markdown_html,
            html_preview_text=html_preview_text,
            html_preview_html=html_preview_html,
            title=title,
            department=department,
            cached_at=datetime.now(UTC).isoformat(),
            original_content=original_content,
        )
        self._save_original_content(cached.news_item_id, cached.file_name, original_content)
        index = self._load_index()
        index[item.news_item_id] = {
            "file_name": cached.file_name,
            "markdown_text": cached.markdown_text,
            "markdown_html": cached.markdown_html,
            "html_preview_text": cached.html_preview_text,
            "html_preview_html": cached.html_preview_html,
            "title": cached.title,
            "department": cached.department,
            "cached_at": cached.cached_at,
        }
        self._save_index(index)
        return cached

    def _build_missing_hwpx_notice(self, item: PolicyBriefingItem, *, file_name: str, detail: str) -> PolicyBriefingCachedDocument:
        title = item.title.strip() or file_name
        department = item.department.strip() or None
        message = "국정브리핑에 HWPX 파일이 없습니다."
        description = "제공기관 첨부가 HWP 형식이거나 HWPX가 제공되지 않아 자동 변환을 진행할 수 없습니다."
        detail_line = detail.strip()
        markdown_lines = [
            f"# {title}",
            "",
            f"> {message}",
            f"> {description}",
        ]
        if detail_line:
            markdown_lines.append(f"> {detail_line}")
        markdown = "\n".join(markdown_lines).strip() + "\n"
        preview_html = "\n".join(
            [
                '<div style="min-height:68vh;display:flex;align-items:center;justify-content:center;padding:24px;">',
                '<div style="max-width:720px;width:100%;text-align:center;border:1px solid #d8d8d8;border-radius:18px;padding:40px 28px;background:#fff;">',
                f'<div style="font-size:30px;font-weight:700;line-height:1.35;color:#161616;margin-bottom:14px;">{escape(message)}</div>',
                f'<div style="font-size:18px;line-height:1.7;color:#424242;margin-bottom:10px;">{escape(description)}</div>',
                (f'<div style="font-size:15px;line-height:1.6;color:#6b6b6b;">{escape(detail_line)}</div>' if detail_line else ""),
                "</div>",
                "</div>",
            ]
        )
        return self.save(
            item=item,
            file_name=file_name,
            markdown_text=markdown,
            markdown_html=markdown,
            html_preview_text=preview_html,
            html_preview_html=preview_html,
            title=title,
            department=department,
            original_content=b"",
        )

    def warm_item(self, item: PolicyBriefingItem) -> PolicyBriefingCachedDocument:
        cached = self.get(item.news_item_id)
        if cached is not None and cached.original_content is not None:
            return cached
        try:
            downloaded = self._client.download_item_hwpx(item)
        except ValueError:
            fallback_name = item.primary_hwpx.file_name if item.primary_hwpx else (item.primary_pdf.file_name if item.primary_pdf else f"{item.title}.hwpx")
            return self._build_missing_hwpx_notice(
                item,
                file_name=fallback_name,
                detail="국정브리핑 제공 첨부에 변환 가능한 HWPX 원문이 없습니다.",
            )
        if not downloaded.is_zip_container:
            return self._build_missing_hwpx_notice(
                item,
                file_name=downloaded.attachment.file_name,
                detail="국정브리핑 첨부는 .hwpx 확장자이지만 실제로는 HWP 형식입니다.",
            )
        if cached is not None:
            self._save_original_content(item.news_item_id, cached.file_name, downloaded.content)
            return PolicyBriefingCachedDocument(
                news_item_id=cached.news_item_id,
                file_name=cached.file_name,
                markdown_text=cached.markdown_text,
                markdown_html=cached.markdown_html,
                html_preview_text=cached.html_preview_text,
                html_preview_html=cached.html_preview_html,
                title=cached.title,
                department=cached.department,
                cached_at=cached.cached_at,
                original_content=downloaded.content,
            )

        from . import hwpx_converter, opendataloader

        with tempfile.NamedTemporaryFile(suffix=".hwpx", delete=False) as handle:
            temp_path = Path(handle.name)
            handle.write(downloaded.content)
        try:
            markdown_text = hwpx_converter.convert_hwpx(str(temp_path), table_mode="text")
            markdown_html = hwpx_converter.convert_hwpx(str(temp_path), table_mode="html")
        finally:
            temp_path.unlink(missing_ok=True)

        markdown_text = _inject_policy_briefing_department(markdown_text, item.department)
        markdown_html = _inject_policy_briefing_department(markdown_html, item.department)
        html_preview_text = opendataloader.render_preview_html(markdown_text)
        html_preview_html = opendataloader.render_preview_html(markdown_html)
        title, department = opendataloader.extract_metadata(markdown_text)
        return self.save(
            item=item,
            markdown_text=markdown_text,
            markdown_html=markdown_html,
            html_preview_text=html_preview_text,
            html_preview_html=html_preview_html,
            title=title,
            department=department,
            original_content=downloaded.content,
        )

    def warm_items(self, items: list[PolicyBriefingItem]) -> list[PolicyBriefingCachedDocument]:
        warmed: list[PolicyBriefingCachedDocument] = []
        for item in items:
            warmed.append(self.warm_item(item))
        return warmed

    def reset(self) -> int:
        index = self._load_index()
        deleted_entries = len(index)
        self._index_path.unlink(missing_ok=True)
        for path in self._originals_dir.glob("*"):
            path.unlink(missing_ok=True)
        return deleted_entries

    def _load_index(self) -> dict[str, object]:
        if not self._index_path.exists():
            return {}
        payload = json.loads(self._index_path.read_text())
        return payload if isinstance(payload, dict) else {}

    def _save_index(self, index: dict[str, object]) -> None:
        self._index_path.write_text(json.dumps(index, ensure_ascii=False, indent=2))

    def _original_path(self, news_item_id: str, file_name: str) -> Path:
        safe_name = re.sub(r"[^\w\s.\-()]", "_", Path(file_name).name) or "document.hwpx"
        return self._originals_dir / f"{news_item_id}-{safe_name}"

    def _save_original_content(self, news_item_id: str, file_name: str, content: bytes) -> None:
        self._original_path(news_item_id, file_name).write_bytes(content)

    def _load_original_content(self, news_item_id: str, file_name: str) -> bytes | None:
        path = self._original_path(news_item_id, file_name)
        if not path.exists():
            return None
        content = path.read_bytes()
        return content or None


def _serialize_item(item: PolicyBriefingItem) -> dict[str, object]:
    return {
        "news_item_id": item.news_item_id,
        "title": item.title,
        "department": item.department,
        "approve_date": item.approve_date,
        "original_url": item.original_url,
        "attachments": [
            {"file_name": attachment.file_name, "file_url": attachment.file_url}
            for attachment in item.attachments
        ],
    }


def normalize_policy_briefing_title_key(text: str) -> str:
    normalized = text.strip().lower()
    normalized = normalized.replace("ai", "인공지능")
    normalized = normalized.replace("a.i.", "인공지능")
    normalized = normalized.replace("_", " ")
    normalized = re.sub(r"\s+", " ", normalized)
    normalized = re.sub(r"[^\w\s()-]", "", normalized)
    return normalized.strip()


def _tokenize_policy_briefing_title_key(text: str) -> list[str]:
    normalized = normalize_policy_briefing_title_key(text)
    if not normalized:
        return []
    compact = normalized.replace(" ", "")
    raw_tokens = re.split(r"[\s()/-]+", normalized)
    tokens: list[str] = []
    for token in raw_tokens:
        token = token.strip()
        if len(token) < 2:
            continue
        if token in {"보도자료", "보도참고", "보도참고자료", "국정브리핑"}:
            continue
        tokens.append(token)
    if compact and compact not in tokens:
        tokens.append(compact)
    return tokens


def find_cached_policy_briefing_by_title(catalog: PolicyBriefingCatalog, query: str) -> PolicyBriefingItem | None:
    normalized_query = normalize_policy_briefing_title_key(query)
    if not normalized_query:
        return None

    query_tokens = _tokenize_policy_briefing_title_key(query)
    exact_matches: list[PolicyBriefingItem] = []
    partial_matches: list[PolicyBriefingItem] = []
    token_matches: list[tuple[int, PolicyBriefingItem]] = []
    for item in catalog.iter_cached_items():
        normalized_title = normalize_policy_briefing_title_key(item.title)
        if not normalized_title:
            continue
        if normalized_title == normalized_query:
            exact_matches.append(item)
        elif normalized_query in normalized_title:
            partial_matches.append(item)
        elif query_tokens:
            compact_title = normalized_title.replace(" ", "")
            matched = sum(1 for token in query_tokens if token in normalized_title or token in compact_title)
            if matched:
                token_matches.append((matched, item))
    if exact_matches:
        return exact_matches[0]
    if partial_matches:
        return partial_matches[0]
    if token_matches:
        token_matches.sort(key=lambda entry: entry[0], reverse=True)
        best_score, best_item = token_matches[0]
        threshold = max(2, min(len(query_tokens), 3))
        if best_score >= threshold:
            return best_item
    return None


def _inject_policy_briefing_department(markdown: str, department: str | None) -> str:
    dept = (department or "").strip()
    if not markdown or not dept:
        return markdown

    lines = markdown.splitlines()
    for index, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            continue
        match = _PRESS_LABEL_RE.fullmatch(stripped)
        if match:
            lines[index] = f"{dept} {match.group(1)} /"
            return "\n".join(lines) + ("\n" if markdown.endswith("\n") else "")
        if index >= 9:
            break
    return markdown


def _deserialize_item(payload: dict[str, object]) -> PolicyBriefingItem:
    attachments = tuple(
        PolicyBriefingAttachment(
            file_name=str(attachment.get("file_name", "")),
            file_url=str(attachment.get("file_url", "")),
        )
        for attachment in payload.get("attachments", [])
        if isinstance(attachment, dict)
    )
    return PolicyBriefingItem(
        news_item_id=str(payload.get("news_item_id", "")),
        title=_normalize_policy_briefing_title(str(payload.get("title", ""))),
        department=str(payload.get("department", "")),
        approve_date=str(payload.get("approve_date", "")),
        original_url=str(payload.get("original_url", "")),
        attachments=attachments,
    )


def _item_sort_key(item: PolicyBriefingItem) -> tuple[str, str]:
    try:
        approved_at = datetime.strptime(item.approve_date, "%m/%d/%Y %H:%M:%S")
        approved_key = approved_at.isoformat()
    except ValueError:
        approved_key = item.approve_date
    return (approved_key, item.news_item_id)


def _matches_target_date(item: PolicyBriefingItem, target_date: date) -> bool:
    try:
        approved_at = datetime.strptime(item.approve_date, "%m/%d/%Y %H:%M:%S")
    except ValueError:
        return False
    return approved_at.date() == target_date


def _approve_date_to_iso(approve_date: str) -> str | None:
    try:
        approved_at = datetime.strptime(approve_date, "%m/%d/%Y %H:%M:%S")
    except ValueError:
        return None
    return approved_at.date().isoformat()


def _extract_attachment_pairs(node: ET.Element) -> list[tuple[str, str]]:
    file_names = [unescape((entry.text or "").strip()) for entry in node.findall("FileName")]
    file_urls = [(entry.text or "").strip() for entry in node.findall("FileUrl")]
    return list(zip(file_names, file_urls))


def _should_refresh_catalog(store: dict[str, object], target_date: date, today: date) -> bool:
    """
    카탈로그 갱신 여부 결정.
    - 이전 날짜: 아이템이 없으면 갱신
    - 당일: 1시간마다 갱신
    """
    if target_date < today:
        return len(store.get("items", {})) == 0

    # 당일 갱신 체크: 1시간 이상 경과했으면 갱신
    last_refreshed_at = store.get("last_refreshed_at", "")
    if not last_refreshed_at:
        return True

    try:
        last = datetime.fromisoformat(last_refreshed_at)
        elapsed = (datetime.now(UTC) - last).total_seconds()
        return elapsed >= _CATALOG_REFRESH_INTERVAL_SECONDS
    except ValueError:
        return True
