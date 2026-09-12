"""Descoberta de PDFs em repositórios institucionais."""

import re
from urllib.parse import urljoin, urlparse

import requests

from src.config import BDTD_PAGE_TIMEOUT, BDTD_REQUEST_TIMEOUT
from src.crawler.download_utils import (
    HEADERS, download_with_browser_context, download_with_requests,
)

IGNORED_CANDIDATE_TERMS = {
    "bitstream-request-a-copy", "file-download-link", "item.edit.bitstreams",
    "item.page.filesection", "statistics.table", "submission.sections",
}


def result(success, reason=None, source_url=None, pdf_url=None, path=None):
    """Cria o contrato público padronizado do parser."""
    return {
        "success": success, "reason": reason, "source_url": source_url,
        "pdf_url": pdf_url, "path": str(path) if path is not None else None,
    }


def alternative_urls(url):
    urls = [url]
    if url.startswith("http://"):
        urls.append("https://" + url[len("http://"):])
    return urls


def is_direct_pdf_url(url):
    return url.lower().split("?", 1)[0].split("#", 1)[0].endswith(".pdf")


def detect_special_page(page):
    """Detecta bloqueios visíveis; não tenta contorná-los."""
    try:
        title = page.title().lower()
    except Exception:
        title = ""
    try:
        text = page.locator("body").inner_text(timeout=5000).lower()
    except Exception:
        text = ""
    combined = f"{title}\n{text}"
    anti_bot = (
        "client verifying", "safeline waf", "checking your browser", "captcha",
        "verificação de segurança", "verificacao de seguranca", "security detection",
    )
    if any(term in combined for term in anti_bot):
        return "anti_bot"
    # Expressões específicas evitam classificar strings internas da interface.
    restricted = (
        "tipo de acesso: acesso embargado", "acesso embargado",
        "restricted access", "arquivo restrito", "acesso restrito",
    )
    if any(term in text for term in restricted):
        return "restricted_or_embargo"
    if any(term in combined for term in ("404 not found", "page not found", "página não encontrada")):
        return "not_found"
    if any(term in combined for term in ("service unavailable", "cannot connect to server")):
        return "repository_unavailable"
    return None


def score_candidate(url, text=""):
    """Prioriza PDFs e bitstreams reais, rejeitando chaves internas/i18n."""
    lower_url = url.lower()
    lower_text = (text or "").lower()
    if not lower_url.startswith(("http://", "https://")):
        return -100
    if any(term in lower_url or term in lower_text for term in IGNORED_CANDIDATE_TERMS):
        return -100
    score = 0
    if ".pdf" in lower_url:
        score += 40
    if "/bitstream/" in lower_url or "/bitstreams/" in lower_url:
        score += 30
    if "download" in lower_url:
        score += 20
    if "pdf" in lower_text or "texto completo" in lower_text:
        score += 15
    return score


def find_pdf_candidates(page):
    """Obtém candidatos dos links renderizados e do HTML da página."""
    candidates = {}
    try:
        links = page.locator("a[href]")
        for index in range(links.count()):
            element = links.nth(index)
            href = element.get_attribute("href")
            if not href:
                continue
            url = urljoin(page.url, href)
            try:
                text = element.inner_text().strip()
            except Exception:
                text = ""
            candidate_score = score_candidate(url, text)
            if candidate_score > 0:
                candidates[url] = max(candidates.get(url, -100), candidate_score)
    except Exception:
        pass
    try:
        html = page.content()
        for found in re.findall(r'https?://[^\s"\'<>]+', html):
            url = found.replace("&amp;", "&")
            candidate_score = score_candidate(url)
            if candidate_score > 0:
                candidates[url] = max(candidates.get(url, -100), candidate_score)
    except Exception:
        pass
    return [url for url, _ in sorted(candidates.items(), key=lambda item: item[1], reverse=True)]


def try_download(context, url, output_file, source_url, referer=None):
    for candidate_url in alternative_urls(url):
        response = download_with_requests(candidate_url, output_file, referer, source_url)
        if response["success"]:
            return response
        response = download_with_browser_context(context, candidate_url, output_file, referer, source_url)
        if response["success"]:
            return response
    return result(False, "not_pdf", source_url, url)


def try_dspace_item_api(repository_url, output_file):
    """Consulta a API de itens do DSpace moderno."""
    match = re.search(r"/items/([0-9a-fA-F-]{36})", repository_url)
    if not match:
        return result(False, "not_dspace_item", repository_url)
    parsed = urlparse(repository_url)
    base = f"{parsed.scheme}://{parsed.netloc}"
    try:
        bundles_response = requests.get(
            f"{base}/server/api/core/items/{match.group(1)}/bundles",
            headers=HEADERS, timeout=BDTD_REQUEST_TIMEOUT, verify=False,
        )
        if not bundles_response.ok:
            return result(False, "dspace_api_failed", repository_url)
        bundles = bundles_response.json().get("_embedded", {}).get("bundles", [])
        for bundle in bundles:
            if bundle.get("name", "").upper() != "ORIGINAL" or not bundle.get("uuid"):
                continue
            bitstreams_response = requests.get(
                f"{base}/server/api/core/bundles/{bundle['uuid']}/bitstreams",
                headers=HEADERS, timeout=BDTD_REQUEST_TIMEOUT, verify=False,
            )
            if not bitstreams_response.ok:
                continue
            bitstreams = bitstreams_response.json().get("_embedded", {}).get("bitstreams", [])
            for bitstream in bitstreams:
                uuid = bitstream.get("uuid")
                if uuid and bitstream.get("name", "").lower().endswith(".pdf"):
                    pdf_url = f"{base}/server/api/core/bitstreams/{uuid}/content"
                    downloaded = download_with_requests(pdf_url, output_file, repository_url, repository_url)
                    if downloaded["success"]:
                        return downloaded
    except requests.exceptions.Timeout:
        return result(False, "timeout", repository_url)
    except requests.exceptions.RequestException:
        return result(False, "http_error", repository_url)
    return result(False, "dspace_pdf_not_found", repository_url)


def open_repository(page, url):
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=BDTD_PAGE_TIMEOUT)
        page.wait_for_timeout(3000)
        return True
    except Exception:
        return False


def process_repository_url(page, context, repository_url, output_file):
    """Descobre e baixa o PDF mantendo um contrato único de resultado."""
    if output_file.exists():
        return result(True, source_url=repository_url, path=output_file)
    if is_direct_pdf_url(repository_url):
        direct = try_download(context, repository_url, output_file, repository_url)
        if direct["success"]:
            return direct
    if "/items/" in repository_url:
        dspace = try_dspace_item_api(repository_url, output_file)
        if dspace["success"]:
            return dspace
    opened_url = repository_url
    if not open_repository(page, opened_url) and repository_url.startswith("http://"):
        opened_url = "https://" + repository_url[len("http://"):]
        if not open_repository(page, opened_url):
            return result(False, "repository_unavailable", repository_url)
    elif not page.url:
        return result(False, "repository_unavailable", repository_url)
    special = detect_special_page(page)
    if special:
        return result(False, special, repository_url)
    if "/items/" in page.url:
        dspace = try_dspace_item_api(page.url, output_file)
        if dspace["success"]:
            dspace["source_url"] = repository_url
            return dspace
    for candidate in find_pdf_candidates(page)[:15]:
        downloaded = try_download(context, candidate, output_file, repository_url, page.url)
        if downloaded["success"]:
            return downloaded
    return result(False, "pdf_not_found", repository_url)


__all__ = ["detect_special_page", "find_pdf_candidates", "process_repository_url", "score_candidate"]
