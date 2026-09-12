import json
import re
import time
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
import urllib3
from playwright.sync_api import sync_playwright


# ============================================================
# CONFIGURAÇÕES
# ============================================================

METADATA_DIR = Path("data/raw/metadata/records")
PDF_DIR = Path("data/raw/pdf")
MANIFEST_DIR = Path("data/raw/manifests")

MAX_RECORDS = 100

REQUEST_TIMEOUT = 20
PAGE_TIMEOUT = 30000

MAX_RETRIES = 2
RETRY_WAIT_SECONDS = 3

urllib3.disable_warnings(
    urllib3.exceptions.InsecureRequestWarning
)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/151.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,"
        "application/xml;q=0.9,"
        "application/pdf;q=0.8,*/*;q=0.7"
    ),
}


# ============================================================
# UTILITÁRIOS DE ARQUIVO
# ============================================================

def load_metadata_files():
    return sorted(
        METADATA_DIR.glob("*.json")
    )[:MAX_RECORDS]


def load_metadata(path):
    with open(
        path,
        "r",
        encoding="utf-8",
    ) as file:
        return json.load(file)


def save_json(path, data):
    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    with open(
        path,
        "w",
        encoding="utf-8",
    ) as file:
        json.dump(
            data,
            file,
            ensure_ascii=False,
            indent=2,
        )


# ============================================================
# URLs
# ============================================================

def split_access_urls(value):
    if not value:
        return []

    if isinstance(value, list):
        values = value
    else:
        values = str(value).splitlines()

    urls = []

    for value in values:
        for part in value.split():
            part = part.strip()

            if part.startswith(
                ("http://", "https://")
            ):
                if part not in urls:
                    urls.append(part)

    return urls


def alternative_urls(url):
    urls = [url]

    if url.startswith("http://"):
        https_url = (
            "https://"
            + url[len("http://"):]
        )

        if https_url not in urls:
            urls.append(https_url)

    return urls


def is_direct_pdf_url(url):
    clean = (
        url.lower()
        .split("?")[0]
        .split("#")[0]
    )

    return clean.endswith(".pdf")


def content_is_pdf(response):
    content_type = (
        response.headers
        .get("Content-Type", "")
        .lower()
    )

    return (
        "application/pdf" in content_type
        or response.content.startswith(b"%PDF")
    )


# ============================================================
# DOWNLOAD COM REQUESTS
# ============================================================

def download_with_requests(
    url,
    output_file,
    referer=None,
    retries=MAX_RETRIES,
):
    headers = HEADERS.copy()

    if referer:
        headers["Referer"] = referer

    for attempt in range(
        1,
        retries + 1,
    ):
        try:
            print(
                f"Tentativa de download "
                f"{attempt}/{retries}"
            )

            response = requests.get(
                url,
                headers=headers,
                timeout=REQUEST_TIMEOUT,
                allow_redirects=True,
                verify=True,
            )

            if response.status_code == 429:
                wait = (
                    RETRY_WAIT_SECONDS
                    * attempt
                    * 2
                )

                print(
                    f"429 recebido. "
                    f"Aguardando {wait}s..."
                )

                time.sleep(wait)
                continue

            response.raise_for_status()

            if not content_is_pdf(
                response
            ):
                print(
                    "Resposta recebida, "
                    "mas não parece ser PDF."
                )

                return {
                    "success": False,
                    "reason": "not_pdf",
                    "url": url,
                    "final_url": response.url,
                }

            output_file.parent.mkdir(
                parents=True,
                exist_ok=True,
            )

            output_file.write_bytes(
                response.content
            )

            return {
                "success": True,
                "url": response.url,
                "path": str(output_file),
            }

        except requests.exceptions.SSLError:
            print(
                "Erro SSL. Tentando sem "
                "validar certificado..."
            )

            try:
                response = requests.get(
                    url,
                    headers=headers,
                    timeout=REQUEST_TIMEOUT,
                    allow_redirects=True,
                    verify=False,
                )

                response.raise_for_status()

                if not content_is_pdf(
                    response
                ):
                    return {
                        "success": False,
                        "reason": "not_pdf_ssl",
                        "url": url,
                    }

                output_file.parent.mkdir(
                    parents=True,
                    exist_ok=True,
                )

                output_file.write_bytes(
                    response.content
                )

                return {
                    "success": True,
                    "url": response.url,
                    "path": str(output_file),
                }

            except Exception as error:
                print(
                    f"Retry SSL falhou: {error}"
                )

        except requests.exceptions.Timeout:
            print(
                "Timeout no download."
            )

        except requests.exceptions.ConnectionError as error:
            print(
                f"Erro de conexão: {error}"
            )

        except Exception as error:
            print(
                f"Erro no download: {error}"
            )

        if attempt < retries:
            wait = (
                RETRY_WAIT_SECONDS
                * attempt
            )

            print(
                f"Aguardando {wait}s..."
            )

            time.sleep(wait)

    return {
        "success": False,
        "reason": "download_failed",
        "url": url,
    }


# ============================================================
# PLAYWRIGHT REQUEST
# ============================================================

def download_with_browser_context(
    context,
    url,
    output_file,
    referer=None,
):
    try:
        headers = {
            "Accept": (
                "application/pdf,"
                "application/octet-stream,*/*"
            )
        }

        if referer:
            headers["Referer"] = referer

        response = context.request.get(
            url,
            headers=headers,
            timeout=PAGE_TIMEOUT,
        )

        if not response.ok:
            return {
                "success": False,
                "reason": (
                    f"http_{response.status}"
                ),
                "url": url,
            }

        body = response.body()

        content_type = (
            response.headers
            .get("content-type", "")
            .lower()
        )

        if (
            "application/pdf"
            not in content_type
            and not body.startswith(b"%PDF")
        ):
            return {
                "success": False,
                "reason": "browser_not_pdf",
                "url": url,
            }

        output_file.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        output_file.write_bytes(body)

        return {
            "success": True,
            "url": url,
            "path": str(output_file),
        }

    except Exception as error:
        print(
            f"Browser context falhou: "
            f"{error}"
        )

        return {
            "success": False,
            "reason": (
                "browser_context_failed"
            ),
            "url": url,
        }


# ============================================================
# CHROMIUM REAL
# ============================================================

def download_direct_with_page(
    page,
    url,
    output_file,
):
    try:
        print(
            "Tentando abrir no "
            "Chromium real..."
        )

        response = page.goto(
            url,
            wait_until="commit",
            timeout=PAGE_TIMEOUT,
        )

        if not response:
            return {
                "success": False,
                "reason": "no_response",
                "url": url,
            }

        try:
            body = response.body()
        except Exception as error:
            print(
                f"Falha ao ler corpo: "
                f"{error}"
            )

            return {
                "success": False,
                "reason": (
                    "chromium_body_failed"
                ),
                "url": url,
            }

        content_type = (
            response.headers
            .get("content-type", "")
            .lower()
        )

        if (
            "application/pdf"
            not in content_type
            and not body.startswith(b"%PDF")
        ):
            return {
                "success": False,
                "reason": "chromium_not_pdf",
                "url": url,
            }

        output_file.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        output_file.write_bytes(body)

        return {
            "success": True,
            "url": response.url,
            "path": str(output_file),
        }

    except Exception as error:
        print(
            f"Chromium real falhou: "
            f"{error}"
        )

        return {
            "success": False,
            "reason": (
                "chromium_page_failed"
            ),
            "url": url,
        }


# ============================================================
# PDF DIRETO
# ============================================================

def try_direct_pdf(
    page,
    context,
    repository_url,
    output_file,
):
    for candidate_url in (
        alternative_urls(
            repository_url
        )
    ):
        print(
            "\nTentando PDF direto:"
        )
        print(candidate_url)

        result = download_with_requests(
            candidate_url,
            output_file,
        )

        if result["success"]:
            return result

        result = download_with_browser_context(
            context,
            candidate_url,
            output_file,
        )

        if result["success"]:
            return result

        result = download_direct_with_page(
            page,
            candidate_url,
            output_file,
        )

        if result["success"]:
            return result

    return {
        "success": False,
        "reason": "direct_pdf_failed",
        "url": repository_url,
    }


# ============================================================
# DETECÇÃO DE BLOQUEIOS / EMBARGO
# ============================================================

def detect_special_page(page):
    try:
        title = page.title().lower()
    except Exception:
        title = ""

    try:
        text = page.locator("body").inner_text(
            timeout=5000
        ).lower()
    except Exception:
        text = ""

    combined = f"{title}\n{text}"

    anti_bot_terms = [
        "client verifying",
        "verificação de segurança",
        "verificacao de seguranca",
        "safeline waf",
        "checking your browser",
        "just a moment",
        "um momento",
        "security detection",
    ]

    for term in anti_bot_terms:
        if term in combined:
            return "anti_bot"

    embargo_terms = [
        "acesso embargado",
        "restricted access",
        "acesso restrito",
        "arquivo restrito",
        "restricted",
        "embargo",
    ]

    for term in embargo_terms:
        if term in combined:
            return "restricted_or_embargo"

    not_found_terms = [
        "page not found",
        "página não encontrada",
        "pagina nao encontrada",
        "404 not found",
    ]

    for term in not_found_terms:
        if term in combined:
            return "not_found"

    unavailable_terms = [
        "service unavailable",
        "cannot connect to server",
    ]

    for term in unavailable_terms:
        if term in combined:
            return "repository_unavailable"

    return None


# ============================================================
# DSPACE MODERNO
# ============================================================

def try_dspace_item_api(
    repository_url,
    output_file,
):
    match = re.search(
        r"/items/([0-9a-fA-F-]{36})",
        repository_url,
    )

    if not match:
        return {
            "success": False,
            "reason": "not_dspace_item",
        }

    item_uuid = match.group(1)

    parsed = urlparse(
        repository_url
    )

    base = (
        f"{parsed.scheme}://"
        f"{parsed.netloc}"
    )

    print(
        "Detectado DSpace moderno."
    )

    print(
        f"UUID: {item_uuid}"
    )

    bundles_url = (
        f"{base}/server/api/core/"
        f"items/{item_uuid}/bundles"
    )

    try:
        response = requests.get(
            bundles_url,
            headers=HEADERS,
            timeout=REQUEST_TIMEOUT,
            verify=False,
        )

        if not response.ok:
            return {
                "success": False,
                "reason": (
                    "dspace_api_failed"
                ),
            }

        data = response.json()

        bundles = (
            data.get(
                "_embedded",
                {},
            )
            .get(
                "bundles",
                [],
            )
        )

        for bundle in bundles:
            name = (
                bundle.get(
                    "name",
                    "",
                )
            )

            if name.upper() != "ORIGINAL":
                continue

            bundle_uuid = (
                bundle.get(
                    "uuid"
                )
            )

            if not bundle_uuid:
                continue

            bitstreams_url = (
                f"{base}/server/api/"
                f"core/bundles/"
                f"{bundle_uuid}/bitstreams"
            )

            bitstreams_response = (
                requests.get(
                    bitstreams_url,
                    headers=HEADERS,
                    timeout=REQUEST_TIMEOUT,
                    verify=False,
                )
            )

            if not bitstreams_response.ok:
                continue

            bitstreams = (
                bitstreams_response.json()
                .get(
                    "_embedded",
                    {},
                )
                .get(
                    "bitstreams",
                    [],
                )
            )

            for bitstream in bitstreams:
                filename = (
                    bitstream.get(
                        "name",
                        "",
                    )
                )

                bitstream_uuid = (
                    bitstream.get(
                        "uuid"
                    )
                )

                if not bitstream_uuid:
                    continue

                if not filename.lower().endswith(
                    ".pdf"
                ):
                    continue

                pdf_url = (
                    f"{base}/server/api/"
                    f"core/bitstreams/"
                    f"{bitstream_uuid}/content"
                )

                print(
                    "PDF encontrado "
                    "pela API DSpace:"
                )
                print(filename)

                result = download_with_requests(
                    pdf_url,
                    output_file,
                    referer=repository_url,
                )

                if result["success"]:
                    return result

    except Exception as error:
        print(
            f"Erro consultando API "
            f"DSpace: {error}"
        )

    return {
        "success": False,
        "reason": (
            "dspace_pdf_not_found"
        ),
    }


# ============================================================
# EXTRAÇÃO DE CANDIDATOS
# ============================================================

def score_candidate(
    url,
    text,
):
    lower_url = url.lower()

    lower_text = (
        text.lower()
        if text
        else ""
    )

    if url.startswith(
        (
            "mailto:",
            "javascript:",
            "tel:",
        )
    ):
        return -100

    score = 0

    if ".pdf" in lower_url:
        score += 40

    if "/bitstream/" in lower_url:
        score += 30

    if "/bitstreams/" in lower_url:
        score += 30

    if "download" in lower_url:
        score += 20

    if "pdf" in lower_text:
        score += 15

    if "download" in lower_text:
        score += 10

    if "baixar" in lower_text:
        score += 10

    if "texto completo" in lower_text:
        score += 10

    if "visualizar" in lower_text:
        score += 7

    if "abrir" in lower_text:
        score += 7

    bad_terms = [
        "manual",
        "politica",
        "política",
        "tutorial",
        "banner",
        "logo",
        "favicon",
        "help.html",
        "privacidade",
    ]

    for term in bad_terms:
        if (
            term in lower_url
            or term in lower_text
        ):
            score -= 40

    return score


def collect_candidates_from_links(
    page,
):
    candidates = []

    selectors = [
        "a[href]",
        "iframe[src]",
        "embed[src]",
        "object[data]",
        "source[src]",
    ]

    for selector in selectors:
        locator = page.locator(
            selector
        )

        try:
            count = locator.count()
        except Exception:
            continue

        for i in range(count):
            element = locator.nth(i)

            if selector == "object[data]":
                raw_url = element.get_attribute(
                    "data"
                )
            else:
                raw_url = (
                    element.get_attribute(
                        "href"
                    )
                    or element.get_attribute(
                        "src"
                    )
                )

            if not raw_url:
                continue

            try:
                text = (
                    element.inner_text()
                    .strip()
                )
            except Exception:
                text = ""

            full_url = urljoin(
                page.url,
                raw_url,
            )

            score = score_candidate(
                full_url,
                text,
            )

            if score >= 10:
                candidates.append(
                    {
                        "url": full_url,
                        "text": text,
                        "score": score,
                    }
                )

    return candidates


def collect_candidates_from_html(
    page,
):
    """
    Procura URLs de PDF/bitstream diretamente
    no HTML bruto da página.
    """

    candidates = []

    try:
        html = page.content()
    except Exception:
        return []

    patterns = [
        r'https?://[^"\'>\s]+\.pdf(?:\?[^"\'>\s]*)?',
        r'["\']([^"\']*?/bitstream/[^"\']+)["\']',
        r'["\']([^"\']*?/bitstreams/[^"\']+)["\']',
        r'["\']([^"\']*?download[^"\']*)["\']',
    ]

    for pattern in patterns:
        matches = re.findall(
            pattern,
            html,
            flags=re.IGNORECASE,
        )

        for match in matches:
            if isinstance(match, tuple):
                match = match[0]

            full_url = urljoin(
                page.url,
                match
            )

            score = score_candidate(
                full_url,
                "",
            )

            if score >= 10:
                candidates.append(
                    {
                        "url": full_url,
                        "text": "",
                        "score": score,
                    }
                )

    return candidates


def collect_candidates_from_attributes(
    page,
):
    """
    Alguns sistemas colocam o link real em
    data-url, data-href, data-download etc.
    """

    candidates = []

    locator = page.locator("*")

    try:
        count = locator.count()
    except Exception:
        return []

    attributes = [
        "data-url",
        "data-href",
        "data-download",
        "data-file",
        "data-src",
    ]

    # Limita para não ficar absurdamente lento
    count = min(
        count,
        5000,
    )

    for i in range(count):
        element = locator.nth(i)

        for attribute in attributes:
            try:
                value = (
                    element.get_attribute(
                        attribute
                    )
                )
            except Exception:
                value = None

            if not value:
                continue

            full_url = urljoin(
                page.url,
                value,
            )

            score = score_candidate(
                full_url,
                "",
            )

            if score >= 10:
                candidates.append(
                    {
                        "url": full_url,
                        "text": "",
                        "score": score,
                    }
                )

    return candidates


def find_pdf_candidates(
    page,
):
    candidates = []

    candidates.extend(
        collect_candidates_from_links(
            page
        )
    )

    candidates.extend(
        collect_candidates_from_html(
            page
        )
    )

    candidates.extend(
        collect_candidates_from_attributes(
            page
        )
    )

    candidates.sort(
        key=lambda item: (
            item["score"]
        ),
        reverse=True,
    )

    seen = set()
    unique = []

    for candidate in candidates:
        url = candidate["url"]

        if url in seen:
            continue

        seen.add(url)
        unique.append(candidate)

    return unique


# ============================================================
# FALLBACK DSPACE ANTIGO / HANDLE
# ============================================================

def extract_handle_id(url):
    """
    Exemplo:
    /handle/123456789/75090
    /xmlui/handle/123456789/75090
    /jspui/handle/handle/24028
    """

    match = re.search(
        r"/handle/([^?#]+)",
        url,
        flags=re.IGNORECASE,
    )

    if not match:
        return None

    return match.group(1).strip("/")


def try_old_dspace_candidates(
    page,
    context,
    repository_url,
    output_file,
):
    """
    Recarrega a página tentando caminhos comuns
    do DSpace antigo e procura bitstreams.
    """

    parsed = urlparse(
        repository_url
    )

    base = (
        f"{parsed.scheme}://"
        f"{parsed.netloc}"
    )

    handle_id = extract_handle_id(
        repository_url
    )

    if not handle_id:
        return {
            "success": False,
            "reason": (
                "no_handle_detected"
            ),
        }

    print(
        f"Handle detectado: "
        f"{handle_id}"
    )

    candidate_pages = [
        repository_url,
        f"{base}/handle/{handle_id}",
        f"{base}/xmlui/handle/{handle_id}",
        f"{base}/jspui/handle/{handle_id}",
    ]

    seen_pages = set()

    for candidate_page in (
        candidate_pages
    ):
        if candidate_page in seen_pages:
            continue

        seen_pages.add(candidate_page)

        try:
            print(
                "Tentando variação "
                "DSpace antigo:"
            )
            print(candidate_page)

            page.goto(
                candidate_page,
                wait_until="domcontentloaded",
                timeout=PAGE_TIMEOUT,
            )

            page.wait_for_timeout(
                3000
            )

        except Exception:
            continue

        candidates = (
            find_pdf_candidates(
                page
            )
        )

        print(
            "Candidatos encontrados "
            f"no fallback DSpace: "
            f"{len(candidates)}"
        )

        for candidate in (
            candidates[:15]
        ):
            pdf_url = (
                candidate["url"]
            )

            for candidate_url in (
                alternative_urls(
                    pdf_url
                )
            ):
                result = (
                    download_with_requests(
                        candidate_url,
                        output_file,
                        referer=page.url,
                    )
                )

                if result["success"]:
                    return result

                result = (
                    download_with_browser_context(
                        context,
                        candidate_url,
                        output_file,
                        referer=page.url,
                    )
                )

                if result["success"]:
                    return result

    return {
        "success": False,
        "reason": (
            "old_dspace_pdf_not_found"
        ),
    }


# ============================================================
# ABERTURA DE PÁGINA
# ============================================================

def open_repository(
    page,
    url,
):
    for attempt in range(
        1,
        MAX_RETRIES + 1,
    ):
        try:
            print(
                f"Abrindo repositório "
                f"{attempt}/{MAX_RETRIES}"
            )

            page.goto(
                url,
                wait_until="domcontentloaded",
                timeout=PAGE_TIMEOUT,
            )

            page.wait_for_timeout(
                5000
            )

            return True

        except Exception as error:
            print(
                f"Erro ao abrir: "
                f"{error}"
            )

            if attempt < MAX_RETRIES:
                time.sleep(
                    RETRY_WAIT_SECONDS
                    * attempt
                )

    return False


# ============================================================
# PROCESSA URL
# ============================================================

def process_repository_url(
    page,
    context,
    repository_url,
    output_file,
):
    # ----------------------------------------
    # 1. PDF DIRETO
    # ----------------------------------------

    if is_direct_pdf_url(
        repository_url
    ):
        return try_direct_pdf(
            page,
            context,
            repository_url,
            output_file,
        )

    # ----------------------------------------
    # 2. DSPACE MODERNO
    # ----------------------------------------

    if "/items/" in repository_url:
        result = try_dspace_item_api(
            repository_url,
            output_file,
        )

        if result["success"]:
            return result

    # ----------------------------------------
    # 3. ABRIR PÁGINA
    # ----------------------------------------

    opened = open_repository(
        page,
        repository_url,
    )

    # HTTP -> HTTPS
    if (
        not opened
        and repository_url.startswith(
            "http://"
        )
    ):
        https_url = (
            "https://"
            + repository_url[
                len("http://"):
            ]
        )

        print(
            "HTTP falhou. "
            "Tentando HTTPS:"
        )

        print(
            https_url
        )

        opened = open_repository(
            page,
            https_url,
        )

        if opened:
            repository_url = https_url

    if not opened:
        return {
            "success": False,
            "reason": (
                "repository_unavailable"
            ),
        }

    try:
        title = page.title()
    except Exception:
        title = ""

    print(
        f"Página carregada: "
        f"{title}"
    )

    # ----------------------------------------
    # 4. DETECTA BLOQUEIOS
    # ----------------------------------------

    special = detect_special_page(
        page
    )

    if special:
        print(
            f"Situação especial "
            f"detectada: {special}"
        )

        # anti-bot / embargo / 404:
        # não tentamos burlar
        if special in {
            "anti_bot",
            "restricted_or_embargo",
            "not_found",
            "repository_unavailable",
        }:
            return {
                "success": False,
                "reason": special,
            }

    # ----------------------------------------
    # 5. SE REDIRECIONOU PARA /items/
    # ----------------------------------------

    if "/items/" in page.url:
        result = try_dspace_item_api(
            page.url,
            output_file,
        )

        if result["success"]:
            return result

    # ----------------------------------------
    # 6. PROCURA CANDIDATOS NA PÁGINA
    # ----------------------------------------

    candidates = (
        find_pdf_candidates(
            page
        )
    )

    print(
        "Candidatos encontrados: "
        f"{len(candidates)}"
    )

    for candidate in (
        candidates[:15]
    ):
        pdf_url = (
            candidate["url"]
        )

        print(
            "\nTentando candidato:"
        )
        print(pdf_url)

        for candidate_url in (
            alternative_urls(
                pdf_url
            )
        ):
            result = (
                download_with_requests(
                    candidate_url,
                    output_file,
                    referer=page.url,
                )
            )

            if result["success"]:
                return result

            result = (
                download_with_browser_context(
                    context,
                    candidate_url,
                    output_file,
                    referer=page.url,
                )
            )

            if result["success"]:
                return result

            result = (
                download_direct_with_page(
                    page,
                    candidate_url,
                    output_file,
                )
            )

            if result["success"]:
                return result

    # ----------------------------------------
    # 7. FALLBACK DSPACE ANTIGO
    # ----------------------------------------

    if "/handle/" in repository_url:
        print(
            "Nenhum candidato direto. "
            "Tentando fallback DSpace antigo..."
        )

        result = (
            try_old_dspace_candidates(
                page,
                context,
                repository_url,
                output_file,
            )
        )

        if result["success"]:
            return result

    return {
        "success": False,
        "reason": "pdf_not_found",
    }


# ============================================================
# MAIN
# ============================================================

def run():
    metadata_files = (
        load_metadata_files()
    )

    print(
        f"Registros disponíveis: "
        f"{len(metadata_files)}"
    )

    PDF_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    MANIFEST_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    downloaded_now = 0
    already_exists = 0
    failed = 0

    manifest = []

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False
        )

        context = (
            browser.new_context(
                ignore_https_errors=True
            )
        )

        page = context.new_page()

        for (
            index,
            metadata_file
        ) in enumerate(
            metadata_files,
            start=1,
        ):
            metadata = (
                load_metadata(
                    metadata_file
                )
            )

            record_id = (
                metadata.get(
                    "record_id"
                )
            )

            access_urls = (
                split_access_urls(
                    metadata.get(
                        "access_url"
                    )
                )
            )

            output_file = (
                PDF_DIR
                / f"{record_id}.pdf"
            )

            print(
                "\n"
                + "=" * 70
            )

            print(
                f"[{index}/"
                f"{len(metadata_files)}]"
            )

            print(
                f"Registro: "
                f"{record_id}"
            )

            # --------------------------------
            # JÁ EXISTE
            # --------------------------------

            if output_file.exists():
                print(
                    "PDF já existe. "
                    "Pulando."
                )

                already_exists += 1

                manifest.append(
                    {
                        "record_id": (
                            record_id
                        ),
                        "status": (
                            "already_exists"
                        ),
                        "pdf_path": str(
                            output_file
                        ),
                    }
                )

                continue

            # --------------------------------
            # SEM URL
            # --------------------------------

            if not access_urls:
                print(
                    "Registro sem "
                    "link de acesso."
                )

                failed += 1

                manifest.append(
                    {
                        "record_id": (
                            record_id
                        ),
                        "status": (
                            "no_access_url"
                        ),
                        "reason": (
                            "no_access_url"
                        ),
                    }
                )

                continue

            final_result = None
            successful_url = None

            # --------------------------------
            # TENTA TODAS AS URLs DO REGISTRO
            # --------------------------------

            for access_url in access_urls:
                print(
                    "\nTentando:"
                )

                print(
                    access_url
                )

                result = (
                    process_repository_url(
                        page,
                        context,
                        access_url,
                        output_file,
                    )
                )

                final_result = result

                if result["success"]:
                    successful_url = (
                        access_url
                    )
                    break

                print(
                    "Essa URL não funcionou."
                )

            # --------------------------------
            # SUCESSO
            # --------------------------------

            if (
                final_result
                and final_result[
                    "success"
                ]
            ):
                downloaded_now += 1

                print(
                    "\nPDF salvo em:"
                )

                print(
                    output_file
                )

                manifest.append(
                    {
                        "record_id": (
                            record_id
                        ),
                        "status": (
                            "downloaded"
                        ),
                        "source_url": (
                            successful_url
                        ),
                        "pdf_url": (
                            final_result.get(
                                "url"
                            )
                        ),
                        "pdf_path": str(
                            output_file
                        ),
                    }
                )

            # --------------------------------
            # FALHA
            # --------------------------------

            else:
                failed += 1

                reason = (
                    final_result.get(
                        "reason"
                    )
                    if final_result
                    else "unknown"
                )

                print(
                    "\nNão foi possível "
                    "baixar."
                )

                print(
                    f"Motivo: {reason}"
                )

                manifest.append(
                    {
                        "record_id": (
                            record_id
                        ),
                        "status": "failed",
                        "access_urls": (
                            access_urls
                        ),
                        "reason": reason,
                    }
                )

            # salva após cada registro
            save_json(
                MANIFEST_DIR
                / "download_manifest.json",
                manifest,
            )

            time.sleep(1)

        browser.close()

    failures = [
        item
        for item in manifest
        if item["status"]
        in {
            "failed",
            "no_access_url",
        }
    ]

    save_json(
        MANIFEST_DIR
        / "failed_downloads.json",
        failures,
    )

    total_pdfs = len(
        list(
            PDF_DIR.glob("*.pdf")
        )
    )

    print(
        "\n"
        + "=" * 70
    )

    print(
        "DOWNLOAD FINALIZADO"
    )

    print(
        f"Baixados agora: "
        f"{downloaded_now}"
    )

    print(
        f"Já existentes: "
        f"{already_exists}"
    )

    print(
        f"Falhas: "
        f"{failed}"
    )

    print(
        f"Total de PDFs: "
        f"{total_pdfs}"
    )

    print(
        "\nManifesto:"
    )

    print(
        "data/raw/manifests/"
        "download_manifest.json"
    )

    print(
        "\nFalhas:"
    )

    print(
        "data/raw/manifests/"
        "failed_downloads.json"
    )


if __name__ == "__main__":
    run()