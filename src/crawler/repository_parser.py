"""
Descoberta de PDFs nos repositórios institucionais.

Responsabilidades:
- abrir páginas dos repositórios;
- consultar DSpace moderno;
- descobrir links candidatos;
- ordenar candidatos;
- tentar baixar o PDF encontrado.

Não percorre os registros da BDTD.
Essa responsabilidade pertence ao downloader.py.
"""

import re
import time

from urllib.parse import (
    urljoin,
    urlparse,
)

import requests


from src.crawler.download_utils import (
    HEADERS,
    MAX_RETRIES,
    PAGE_TIMEOUT,
    REQUEST_TIMEOUT,
    RETRY_WAIT_SECONDS,
    alternative_urls,
    download_with_browser_context,
    download_with_requests,
    is_direct_pdf_url,
)

from src.crawler.repository_detection import (
    detect_special_page,
    score_candidate,
    valid_candidate_url,
)


# ============================================================
# DSPACE MODERNO
# ============================================================


def try_dspace_item_api(
    repository_url,
    output_file,
):
    """
    Tenta localizar um PDF utilizando a API REST
    do DSpace 7+.

    É aplicável a URLs no formato:

        /items/<uuid>
    """

    match = re.search(
        r"/items/"
        r"([0-9a-fA-F-]{36})",
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

    bundles_url = (
        f"{base}"
        f"/server/api/core/items/"
        f"{item_uuid}/bundles"
    )

    try:

        response = requests.get(
            bundles_url,
            headers=HEADERS,
            timeout=REQUEST_TIMEOUT,
            verify=False,
        )

        response.raise_for_status()

        bundles = (
            response.json()
            .get("_embedded", {})
            .get("bundles", [])
        )

        for bundle in bundles:

            if (
                bundle.get(
                    "name",
                    "",
                ).upper()
                != "ORIGINAL"
            ):
                continue

            bundle_uuid = (
                bundle.get("uuid")
            )

            if not bundle_uuid:
                continue

            bitstreams_url = (
                f"{base}"
                f"/server/api/core/"
                f"bundles/{bundle_uuid}"
                f"/bitstreams"
            )

            bitstream_response = (
                requests.get(
                    bitstreams_url,
                    headers=HEADERS,
                    timeout=REQUEST_TIMEOUT,
                    verify=False,
                )
            )

            bitstream_response.raise_for_status()

            bitstreams = (
                bitstream_response
                .json()
                .get("_embedded", {})
                .get("bitstreams", [])
            )

            for bitstream in bitstreams:

                filename = (
                    bitstream.get(
                        "name",
                        "",
                    )
                )

                uuid = bitstream.get(
                    "uuid"
                )

                if not uuid:
                    continue

                if not filename.lower().endswith(
                    ".pdf"
                ):
                    continue

                pdf_url = (
                    f"{base}"
                    f"/server/api/core/"
                    f"bitstreams/{uuid}"
                    f"/content"
                )

                result = (
                    download_with_requests(
                        pdf_url,
                        output_file,
                        referer=repository_url,
                    )
                )

                if result["success"]:
                    return result

    except Exception as error:

        print(
            "DSpace API falhou:",
            error,
        )

    return {
        "success": False,
        "reason": (
            "dspace_pdf_not_found"
        ),
    }


# ============================================================
# COLETA DE CANDIDATOS
# ============================================================


def collect_candidates_from_links(
    page,
):
    """
    Procura URLs candidatas nos elementos
    renderizados da página.
    """

    candidates = []

    selectors = [
        ("a[href]", "href"),
        ("iframe[src]", "src"),
        ("embed[src]", "src"),
        ("object[data]", "data"),
        ("source[src]", "src"),
    ]

    for selector, attribute in selectors:

        locator = page.locator(
            selector
        )

        try:
            count = locator.count()

        except Exception:
            continue

        for index in range(count):

            element = locator.nth(
                index
            )

            try:

                raw_url = (
                    element.get_attribute(
                        attribute
                    )
                )

            except Exception:
                raw_url = None

            if not raw_url:
                continue

            url = urljoin(
                page.url,
                raw_url,
            )

            try:

                text = (
                    element.inner_text()
                    .strip()
                )

            except Exception:
                text = ""

            score = score_candidate(
                url,
                text,
            )

            if score > 0:

                candidates.append(
                    {
                        "url": url,
                        "text": text,
                        "score": score,
                    }
                )

    return candidates


def collect_candidates_from_html(
    page,
):
    """
    Procura URLs candidatas diretamente
    no HTML da página.
    """

    try:
        html = page.content()

    except Exception:
        return []

    candidates = []

    patterns = [
        (
            r'https?://'
            r'[^"\'<>\s]+'
            r'\.pdf'
            r'(?:\?[^"\'<>\s]*)?'
        ),
        (
            r'["\']'
            r'([^"\']*/bitstreams/'
            r'[^"\']+/download)'
            r'["\']'
        ),
        (
            r'["\']'
            r'([^"\']*/server/api/core/'
            r'bitstreams/[^"\']+/content)'
            r'["\']'
        ),
    ]

    for pattern in patterns:

        matches = re.findall(
            pattern,
            html,
            flags=re.IGNORECASE,
        )

        for match in matches:

            if isinstance(
                match,
                tuple,
            ):
                match = match[0]

            url = urljoin(
                page.url,
                match,
            )

            score = score_candidate(
                url
            )

            if score > 0:

                candidates.append(
                    {
                        "url": url,
                        "text": "",
                        "score": score,
                    }
                )

    return candidates


def find_pdf_candidates(
    page,
):
    """
    Combina os candidatos encontrados na página,
    remove duplicatas e ordena pela pontuação.
    """

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

    candidates.sort(
        key=lambda item: item[
            "score"
        ],
        reverse=True,
    )

    seen = set()
    result = []

    for candidate in candidates:

        url = candidate["url"]

        if url in seen:
            continue

        if not valid_candidate_url(
            url
        ):
            continue

        seen.add(url)

        result.append(
            candidate
        )

    return result


# ============================================================
# ABERTURA DO REPOSITÓRIO
# ============================================================


def open_repository(
    page,
    repository_url,
):
    """
    Abre a página do repositório utilizando Playwright.

    Faz pequenas tentativas antes de desistir.
    """

    for attempt in range(
        1,
        MAX_RETRIES + 1,
    ):

        try:

            page.goto(
                repository_url,
                wait_until=(
                    "domcontentloaded"
                ),
                timeout=PAGE_TIMEOUT,
            )

            page.wait_for_timeout(
                3000
            )

            return True

        except Exception as error:

            print(
                f"Falha ao abrir: "
                f"{error}"
            )

            if attempt < MAX_RETRIES:

                time.sleep(
                    RETRY_WAIT_SECONDS
                )

    return False


# ============================================================
# PROCESSAMENTO DO REPOSITÓRIO
# ============================================================


def process_repository_url(
    page,
    context,
    repository_url,
    output_file,
):
    """
    Processa uma URL externa fornecida pela BDTD
    e tenta encontrar o PDF correspondente.

    Este é o contrato principal utilizado pelo
    downloader.py.
    """

    # --------------------------------------------------------
    # PDF direto
    # --------------------------------------------------------

    if is_direct_pdf_url(
        repository_url
    ):

        for url in alternative_urls(
            repository_url
        ):

            result = (
                download_with_requests(
                    url,
                    output_file,
                )
            )

            if result["success"]:
                return result

        return {
            "success": False,
            "reason": (
                "direct_pdf_failed"
            ),
        }

    # --------------------------------------------------------
    # DSpace moderno /items/<uuid>
    # --------------------------------------------------------

    if "/items/" in repository_url:

        result = try_dspace_item_api(
            repository_url,
            output_file,
        )

        if result["success"]:
            return result

    # --------------------------------------------------------
    # Abre página do repositório
    # --------------------------------------------------------

    opened = open_repository(
        page,
        repository_url,
    )

    # Alguns repositórios antigos redirecionam melhor
    # quando utilizados via HTTPS.
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

        opened = open_repository(
            page,
            https_url,
        )

        if opened:
            repository_url = (
                https_url
            )

    if not opened:

        return {
            "success": False,
            "reason": (
                "repository_unavailable"
            ),
        }

    print(
        "Página:",
        page.url,
    )

    # --------------------------------------------------------
    # Verifica restrições / anti-bot
    # --------------------------------------------------------

    special = detect_special_page(
        page
    )

    if special:

        return {
            "success": False,
            "reason": special,
        }

    # --------------------------------------------------------
    # Redirecionamento para DSpace moderno
    # --------------------------------------------------------

    if "/items/" in page.url:

        result = try_dspace_item_api(
            page.url,
            output_file,
        )

        if result["success"]:
            return result

    # --------------------------------------------------------
    # Procura links candidatos
    # --------------------------------------------------------

    candidates = find_pdf_candidates(
        page
    )

    print(
        "Candidatos válidos:",
        len(candidates),
    )

    # Mantém o limite do código original.
    for candidate in candidates[
        :10
    ]:

        pdf_url = candidate[
            "url"
        ]

        print(
            "Tentando PDF:",
            pdf_url,
        )

        for url in alternative_urls(
            pdf_url
        ):

            # --------------------------------------------
            # Primeira tentativa: requests
            # --------------------------------------------

            result = (
                download_with_requests(
                    url,
                    output_file,
                    referer=page.url,
                )
            )

            if result["success"]:
                return result

            # --------------------------------------------
            # Segunda tentativa: contexto Playwright
            # --------------------------------------------

            result = (
                download_with_browser_context(
                    context,
                    url,
                    output_file,
                    referer=page.url,
                )
            )

            if result["success"]:
                return result

    return {
        "success": False,
        "reason": "pdf_not_found",
    }