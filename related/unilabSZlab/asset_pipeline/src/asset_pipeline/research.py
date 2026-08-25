from __future__ import annotations

import hashlib
import html
import io
import ipaddress
import json
import re
import socket
from pathlib import Path
from urllib.parse import urljoin, urlparse

import httpx
from ddgs import DDGS
from PIL import Image

from .config import Settings
from .models import CandidateImage, DeviceRecord, Dimensions, ResearchBundle
from .workbook import parse_dimensions_json


class ResearchError(RuntimeError):
    pass


def _safe_public_url(url: str) -> bool:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return False
    if parsed.hostname.casefold() in {"localhost", "localhost.localdomain"}:
        return False
    proxy_range = ipaddress.ip_network("198.18.0.0/15")
    try:
        addresses = {item[4][0] for item in socket.getaddrinfo(parsed.hostname, None)}
        for address in addresses:
            ip = ipaddress.ip_address(address)
            if ip in proxy_range:
                continue
            if not ip.is_global:
                return False
        return True
    except (socket.gaierror, ValueError):
        return False


def _number(value: object) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        match = re.search(r"\d+(?:\.\d+)?", value)
        return float(match.group()) if match else None
    return None


def dimensions_from_device(device: DeviceRecord) -> Dimensions:
    raw = parse_dimensions_json(device.structured_dimensions)
    source = raw.get("尺寸来源URL")
    if isinstance(source, str) and "；" in source:
        source = source.split("；", 1)[0]
    dimensions = Dimensions(
        width_mm=_number(raw.get("宽mm")),
        depth_mm=_number(raw.get("深mm")),
        height_mm=_number(raw.get("高mm")),
        weight_kg=_number(raw.get("重量kg")),
        source_url=source,
        notes=str(raw.get("占地/安装备注", "")),
    )
    dimensions.confidence = (
        0.95
        if dimensions.complete and dimensions.source_url
        else (0.7 if dimensions.complete else 0.2)
    )
    return dimensions


class ImageResearcher:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.client = httpx.Client(
            timeout=httpx.Timeout(30.0),
            follow_redirects=True,
            headers={"User-Agent": "LabAssetPipeline/0.1"},
        )

    def close(self) -> None:
        self.client.close()

    def __enter__(self) -> ImageResearcher:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def query_terms(self, device: DeviceRecord) -> list[str]:
        base = device.manufacturer_model
        return [
            f'"{base}" product',
            f'"{base}" instrument front side rear',
            f'"{base}" dimensions manual pdf',
            f'"{base}" 产品图 尺寸',
        ]

    def search_images(self, query: str, count: int = 50) -> list[dict]:
        brave_results: list[dict] = []
        if self.settings.brave_search_api_key:
            try:
                response = self.client.get(
                    self.settings.brave_image_api_url,
                    headers={
                        "Accept": "application/json",
                        "X-Subscription-Token": self.settings.brave_search_api_key,
                    },
                    params={
                        "q": query,
                        "count": min(count, 200),
                        "country": "ALL",
                        "search_lang": "en",
                        "safesearch": "strict",
                        "spellcheck": "false",
                    },
                )
                response.raise_for_status()
                brave_results = response.json().get("results", [])
                for result in brave_results:
                    result["_official"] = False
                    result["_provider"] = "brave"
            except httpx.HTTPError:
                pass
        try:
            ddgs_raw = DDGS().images(
                query,
                region="wt-wt",
                safesearch="on",
                size="Large",
                max_results=min(count, 100),
            )
        except Exception:
            ddgs_raw = []
        ddgs_results = [
            {
                "properties": {"url": result.get("image", "")},
                "thumbnail": {"src": result.get("thumbnail", "")},
                "page_url": result.get("url", ""),
                "title": result.get("title", ""),
                "source": result.get("source", ""),
                "_official": False,
                "_provider": "ddgs",
            }
            for result in ddgs_raw
        ]
        if not brave_results and not ddgs_results:
            raise ResearchError("Both Brave and DDGS image search failed")
        combined: list[dict] = []
        for index in range(max(len(brave_results), len(ddgs_results))):
            if index < len(brave_results):
                combined.append(brave_results[index])
            if index < len(ddgs_results):
                combined.append(ddgs_results[index])
            if len(combined) >= count:
                break
        return combined

    def search_web(self, query: str, count: int = 10) -> list[dict]:
        if self.settings.brave_search_api_key:
            try:
                response = self.client.get(
                    self.settings.brave_web_api_url,
                    headers={
                        "Accept": "application/json",
                        "X-Subscription-Token": self.settings.brave_search_api_key,
                    },
                    params={
                        "q": query,
                        "count": min(count, 20),
                        "country": "ALL",
                        "search_lang": "en",
                        "safesearch": "strict",
                        "spellcheck": "false",
                    },
                )
                response.raise_for_status()
                results = (response.json().get("web") or {}).get("results", [])
                if results:
                    return results
            except httpx.HTTPError:
                pass
        try:
            results = DDGS().text(
                query,
                region="wt-wt",
                safesearch="on",
                max_results=min(count, 20),
            )
        except Exception:
            return []
        return [
            {
                "title": result.get("title", ""),
                "url": result.get("href", ""),
                "description": result.get("body", ""),
            }
            for result in results
        ]

    def official_images(self, device: DeviceRecord) -> list[dict]:
        results: list[dict] = []
        for page_url in device.official_links:
            if ".pdf" in page_url.casefold() or not _safe_public_url(page_url):
                continue
            try:
                response = self.client.get(page_url)
                response.raise_for_status()
            except httpx.HTTPError:
                continue
            content_type = response.headers.get("content-type", "").casefold()
            if "html" not in content_type:
                continue
            image_urls = self._extract_image_urls(response.text, str(response.url))
            for image_url, title in image_urls:
                results.append(
                    {
                        "properties": {"url": image_url},
                        "page_url": str(response.url),
                        "title": title or device.manufacturer_model,
                        "source": urlparse(str(response.url)).hostname or "official",
                        "_official": True,
                        "_provider": "official",
                    }
                )
        return results

    @staticmethod
    def _extract_image_urls(document: str, page_url: str) -> list[tuple[str, str]]:
        values: list[tuple[str, str]] = []
        meta_pattern = re.compile(
            r'<meta[^>]+(?:property|name)=["\'](?:og:image|twitter:image)["\'][^>]+'
            r'content=["\']([^"\']+)["\']',
            re.I,
        )
        reverse_meta_pattern = re.compile(
            r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+'
            r'(?:property|name)=["\'](?:og:image|twitter:image)["\']',
            re.I,
        )
        for match in [
            *meta_pattern.finditer(document),
            *reverse_meta_pattern.finditer(document),
        ]:
            values.append(
                (
                    urljoin(page_url, html.unescape(match.group(1))),
                    "official hero image",
                )
            )
        image_pattern = re.compile(r"<img\b([^>]+)>", re.I)
        for tag in image_pattern.findall(document):
            source_match = re.search(
                r'(?:src|data-src|data-original)=["\']([^"\']+)["\']', tag, re.I
            )
            if not source_match:
                continue
            alt_match = re.search(r'alt=["\']([^"\']*)["\']', tag, re.I)
            source = html.unescape(source_match.group(1))
            if source.casefold().endswith((".svg", ".gif")):
                continue
            values.append(
                (
                    urljoin(page_url, source),
                    html.unescape(alt_match.group(1)) if alt_match else "",
                )
            )
        unique: dict[str, str] = {}
        for url, title in values:
            if url.startswith(("http://", "https://")):
                unique.setdefault(url, title)
        return list(unique.items())[:30]

    def research(self, device: DeviceRecord) -> ResearchBundle:
        asset_dir = self.settings.asset_dir(device.id)
        candidates_dir = asset_dir / "candidates"
        evidence_dir = asset_dir / "evidence"
        candidates_dir.mkdir(exist_ok=True)
        evidence_dir.mkdir(exist_ok=True)

        queries = self.query_terms(device)
        raw_results: list[dict] = self.official_images(device)
        seen_urls: set[str] = set()
        for result in raw_results:
            direct_url = self._direct_image_url(result)
            if direct_url:
                seen_urls.add(direct_url)
        for query in queries[:3]:
            for result in self.search_images(query):
                direct_url = self._direct_image_url(result)
                if direct_url and direct_url not in seen_urls:
                    seen_urls.add(direct_url)
                    raw_results.append(result)
                if len(raw_results) >= self.settings.image_candidates_per_device * 3:
                    break
            if len(raw_results) >= self.settings.image_candidates_per_device * 3:
                break

        candidates: list[CandidateImage] = []
        for index, result in enumerate(raw_results):
            if len(candidates) >= self.settings.image_candidates_per_device:
                break
            candidate = self._download_candidate(device, result, index, candidates_dir)
            if candidate:
                candidates.append(candidate)

        candidates.sort(key=lambda item: item.score, reverse=True)
        for candidate in candidates[: min(4, len(candidates))]:
            candidate.selected = True
        web_results = self.search_web(queries[2], count=10)
        evidence_urls = list(
            dict.fromkeys(
                device.official_links
                + [
                    str(result.get("url", ""))
                    for result in web_results
                    if result.get("url")
                ]
            )
        )
        (evidence_dir / "web-results.json").write_text(
            json.dumps(web_results, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        self._download_evidence(evidence_urls[:10], evidence_dir)

        bundle = ResearchBundle(
            device_id=device.id,
            query_terms=queries,
            dimensions=dimensions_from_device(device),
            images=candidates,
            evidence_urls=evidence_urls,
            identity_confidence=max((item.score for item in candidates), default=0.0),
            agent_summary="Awaiting Cursor Agent review.",
        )
        (asset_dir / "research.json").write_text(
            bundle.model_dump_json(indent=2), encoding="utf-8"
        )
        return bundle

    @staticmethod
    def _direct_image_url(result: dict) -> str:
        properties = result.get("properties") or {}
        return properties.get("url") or result.get("url") or ""

    def _download_candidate(
        self,
        device: DeviceRecord,
        result: dict,
        index: int,
        directory: Path,
    ) -> CandidateImage | None:
        direct_url = self._direct_image_url(result)
        thumbnail = (result.get("thumbnail") or {}).get("src", "")
        download_url = direct_url if _safe_public_url(direct_url) else thumbnail
        if not download_url or not _safe_public_url(download_url):
            return None
        try:
            response = self.client.get(download_url)
            response.raise_for_status()
            if len(response.content) > 25 * 1024 * 1024:
                return None
            digest = hashlib.sha256(response.content).hexdigest()
            with Image.open(io.BytesIO(response.content)) as image:
                image.load()
                width, height = image.size
                has_alpha = image.mode in {"RGBA", "LA"} or "transparency" in image.info
                suffix = ".png" if has_alpha else ".jpg"
                path = directory / f"{index:02d}-{digest[:10]}{suffix}"
                if has_alpha:
                    image.convert("RGBA").save(path, format="PNG", optimize=True)
                else:
                    image.convert("RGB").save(
                        path, format="JPEG", quality=95, optimize=True
                    )
            if width < 256 or height < 256:
                path.unlink(missing_ok=True)
                return None
            title = str(result.get("title", ""))
            page_url = str(result.get("page_url") or result.get("source") or "")
            source_name = str(result.get("source", ""))
            score = self._score(
                device,
                title,
                page_url,
                width,
                height,
                official=bool(result.get("_official")),
            )
            return CandidateImage(
                id=digest[:16],
                source_url=direct_url,
                page_url=page_url,
                title=title,
                source_name=source_name,
                search_provider=str(result.get("_provider", "")),
                local_path=str(path),
                sha256=digest,
                width=width,
                height=height,
                score=score,
            )
        except (httpx.HTTPError, OSError, Image.UnidentifiedImageError):
            return None

    @staticmethod
    def _score(
        device: DeviceRecord,
        title: str,
        page_url: str,
        width: int,
        height: int,
        official: bool = False,
    ) -> float:
        haystack = f"{title} {page_url}".casefold()
        normalized_haystack = re.sub(r"[^a-z0-9]+", "", haystack)
        tokens = [
            token
            for token in re.split(r"[^\w]+", device.manufacturer_model.casefold())
            if len(token) >= 3
        ]
        model_markers = [
            re.sub(r"[^a-z0-9]+", "", segment.casefold())
            for segment in re.split(r"[\s/]+", device.manufacturer_model)
            if any(char.isdigit() for char in segment)
        ]
        identity = sum(token in haystack for token in tokens) / max(len(tokens), 1)
        resolution = min((width * height) / (1600 * 1200), 1.0)
        official_bonus = (
            0.25
            if official
            else (
                0.15
                if any(
                    domain in page_url.casefold()
                    for domain in (
                        "beckman",
                        "thermofisher",
                        "waters",
                        "revvity",
                        "metrohm",
                        "unchained",
                    )
                )
                else 0.0
            )
        )
        score = min(1.0, identity * 0.6 + resolution * 0.15 + official_bonus)
        if model_markers and any(
            marker not in normalized_haystack for marker in model_markers
        ):
            score *= 0.25
        return score

    def _download_evidence(self, urls: list[str], directory: Path) -> None:
        for index, url in enumerate(urls):
            if not _safe_public_url(url):
                continue
            try:
                response = self.client.get(url)
                response.raise_for_status()
                if len(response.content) > 50 * 1024 * 1024:
                    continue
                content_type = response.headers.get("content-type", "").casefold()
                if "pdf" in content_type or ".pdf" in url.casefold():
                    (directory / f"source-{index:02d}.pdf").write_bytes(
                        response.content
                    )
                elif "text/html" in content_type:
                    text = response.text
                    text = re.sub(
                        r"<script\b[^>]*>.*?</script>", " ", text, flags=re.I | re.S
                    )
                    text = re.sub(
                        r"<style\b[^>]*>.*?</style>", " ", text, flags=re.I | re.S
                    )
                    text = re.sub(r"<[^>]+>", " ", text)
                    text = re.sub(r"\s+", " ", text).strip()
                    (directory / f"source-{index:02d}.txt").write_text(
                        f"URL: {url}\n\n{text[:200_000]}", encoding="utf-8"
                    )
            except httpx.HTTPError:
                continue
