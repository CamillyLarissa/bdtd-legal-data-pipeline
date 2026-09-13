"""
Descoberta e download de PDFs nos repositórios institucionais.

Responsabilidades:
- abrir páginas dos repositórios;
- consultar DSpace moderno;
- identificar links de download;
- reconhecer botões como "Baixar/Abrir";
- priorizar bitstreams e PDFs;
- tentar download via requests;
- usar o contexto do navegador como fallback.

Não percorre registros da BDTD.
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
# CONFIGURAÇÕES
# ============================================================

MAX_CANDIDATES = 20


# ============================================================
# DSPACE MODERNO
# ============================================================

def try_dspace_item_api(
    repository_url,
    output_file,
):
    """
    Tenta localizar um PDF pela API REST
    do DSpace 7+.

    Aplicável principalmente a URLs:

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

            bundle_name = (
                bundle.get(
                    "name",
                    "",
                )
                .upper()
            )

            if bundle_name != "ORIGINAL":
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

                uuid = (
                    bitstream.get(
                        "uuid"
                    )
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

                print(
                    "DSpace API encontrou PDF:"
                )

                print(
                    pdf_url
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
# PONTUAÇÃO ADICIONAL
# ============================================================

def extra_candidate_score(
    url,
    text="",
):
    """
    Adiciona prioridade para padrões comuns
    de páginas DSpace, TEDE e similares.

    Isso complementa score_candidate().
    """

    score = 0

    lower_url = (
        str(url)
        .lower()
        .strip()
    )

    normalized_text = (
        str(text)
        .lower()
        .strip()
    )

    # --------------------------------------------------------
    # Texto do botão/link
    # --------------------------------------------------------

    download_markers = [
        "baixar/abrir",
        "baixar",
        "download",
        "download file",
        "abrir arquivo",
        "acessar arquivo",
        "visualizar arquivo",
        "texto completo",
        "texto parcial",
        "full text",
        "view/open",
        "open file",
    ]

    if any(
        marker in normalized_text
        for marker in download_markers
    ):
        score += 120

    # --------------------------------------------------------
    # URL
    # --------------------------------------------------------

    if "/bitstream/" in lower_url:
        score += 120

    if "/bitstreams/" in lower_url:
        score += 120

    if "/retrieve/" in lower_url:
        score += 100

    if "/download" in lower_url:
        score += 100

    if "/content" in lower_url:
        score += 80

    if ".pdf" in lower_url:
        score += 150

    if lower_url.endswith(".pdf"):
        score += 50

    return score


# ============================================================
# CANDIDATOS A PARTIR DOS LINKS
# ============================================================

def collect_candidates_from_links(
    page,
):
    """
    Procura URLs candidatas nos elementos renderizados
    da página.

    Reconhece:
    - links normais;
    - iframes;
    - embeds;
    - objects;
    - source;
    - botões/link com texto de download.
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

            raw_url = (
                str(raw_url)
                .strip()
            )

            if raw_url.startswith(
                (
                    "javascript:",
                    "mailto:",
                    "#",
                )
            ):
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

            try:
                base_score = (
                    score_candidate(
                        url,
                        text,
                    )
                )

            except Exception:
                base_score = 0

            extra_score = (
                extra_candidate_score(
                    url,
                    text,
                )
            )

            score = (
                base_score
                + extra_score
            )

            if score <= 0:
                continue

            candidates.append(
                {
                    "url": url,
                    "text": text,
                    "score": score,
                }
            )

    return candidates


# ============================================================
# CANDIDATOS A PARTIR DO HTML
# ============================================================

def collect_candidates_from_html(
    page,
):
    """
    Procura URLs diretamente no HTML.

    Útil para páginas em que o link do arquivo
    aparece em scripts ou atributos não capturados
    pelos seletores normais.
    """

    try:
        html = page.content()

    except Exception:
        return []

    candidates = []

    patterns = [
        # URL absoluta terminando em PDF
        (
            r'https?://'
            r'[^"\'<>\s]+'
            r'\.pdf'
            r'(?:\?[^"\'<>\s]*)?'
        ),

        # URLs relativas/absolutas com bitstream
        (
            r'["\']'
            r'([^"\']*/bitstream/'
            r'[^"\']+)'
            r'["\']'
        ),

        # DSpace bitstreams download
        (
            r'["\']'
            r'([^"\']*/bitstreams/'
            r'[^"\']+/download'
            r'[^"\']*)'
            r'["\']'
        ),

        # API DSpace
        (
            r'["\']'
            r'([^"\']*/server/api/core/'
            r'bitstreams/[^"\']+/content)'
            r'["\']'
        ),

        # Retrieve
        (
            r'["\']'
            r'([^"\']*/retrieve/'
            r'[^"\']+)'
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

            try:
                base_score = (
                    score_candidate(
                        url
                    )
                )

            except Exception:
                base_score = 0

            score = (
                base_score
                + extra_candidate_score(
                    url
                )
            )

            if score <= 0:
                continue

            candidates.append(
                {
                    "url": url,
                    "text": "",
                    "score": score,
                }
            )

    return candidates


# ============================================================
# ORDENAÇÃO DOS CANDIDATOS
# ============================================================

def find_pdf_candidates(
    page,
):
    """
    Combina candidatos encontrados no DOM e no HTML,
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

        url = (
            candidate["url"]
            .strip()
        )

        if url in seen:
            continue

        try:
            is_valid = (
                valid_candidate_url(
                    url
                )
            )

        except Exception:
            # Links altamente característicos de arquivo
            # ainda podem ser usados mesmo se a função
            # genérica não os reconhecer.
            is_valid = False

        strong_candidate = (
            extra_candidate_score(
                url,
                candidate.get(
                    "text",
                    "",
                ),
            )
            >= 80
        )

        if (
            not is_valid
            and not strong_candidate
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
    Abre página de repositório utilizando Playwright.

    Tenta novamente em falhas temporárias.
    """

    for attempt in range(
        1,
        MAX_RETRIES + 1,
    ):

        try:
            print(
                f"Abrindo repositório "
                f"(tentativa {attempt}/"
                f"{MAX_RETRIES})..."
            )

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
                "Falha ao abrir:",
                error,
            )

            if attempt < MAX_RETRIES:

                time.sleep(
                    RETRY_WAIT_SECONDS
                )

    return False


# ============================================================
# DOWNLOAD DE UM CANDIDATO
# ============================================================

def try_candidate_download(
    context,
    candidate_url,
    output_file,
    referer,
):
    """
    Tenta baixar um candidato:

    1. requests;
    2. browser context.
    """

    for url in alternative_urls(
        candidate_url
    ):

        print(
            "Tentando PDF:"
        )

        print(
            url
        )

        # ----------------------------------------------------
        # REQUESTS
        # ----------------------------------------------------

        result = (
            download_with_requests(
                url,
                output_file,
                referer=referer,
            )
        )

        if result["success"]:
            return result

        # ----------------------------------------------------
        # PLAYWRIGHT
        # ----------------------------------------------------

        result = (
            download_with_browser_context(
                context,
                url,
                output_file,
                referer=referer,
            )
        )

        if result["success"]:
            return result

    return {
        "success": False,
        "reason": "candidate_failed",
    }


# ============================================================
# PROCESSAMENTO PRINCIPAL
# ============================================================

def process_repository_url(
    page,
    context,
    repository_url,
    output_file,
):
    """
    Processa uma URL externa fornecida pela BDTD
    e tenta localizar o PDF correspondente.

    Contrato utilizado pelo downloader.py.
    """

    repository_url = (
        str(repository_url)
        .strip()
    )

    # ========================================================
    # 1. PDF DIRETO
    # ========================================================

    if is_direct_pdf_url(
        repository_url
    ):

        print(
            "URL parece ser PDF direto."
        )

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

            result = (
                download_with_browser_context(
                    context,
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

    # ========================================================
    # 2. DSPACE MODERNO /items/<uuid>
    # ========================================================

    if "/items/" in repository_url:

        result = try_dspace_item_api(
            repository_url,
            output_file,
        )

        if result["success"]:
            return result

    # ========================================================
    # 3. ABRE PÁGINA DO REPOSITÓRIO
    # ========================================================

    opened = open_repository(
        page,
        repository_url,
    )

    # --------------------------------------------------------
    # Tenta HTTPS para links antigos HTTP
    # --------------------------------------------------------

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
        "Página final:"
    )

    print(
        page.url
    )

    # ========================================================
    # 4. RESTRIÇÕES / ANTI-BOT
    # ========================================================

    special = detect_special_page(
        page
    )

    if special:

        return {
            "success": False,
            "reason": special,
        }

    # ========================================================
    # 5. REDIRECIONAMENTO PARA DSPACE MODERNO
    # ========================================================

    if "/items/" in page.url:

        result = try_dspace_item_api(
            page.url,
            output_file,
        )

        if result["success"]:
            return result

    # ========================================================
    # 6. PROCURA CANDIDATOS
    # ========================================================

    candidates = (
        find_pdf_candidates(
            page
        )
    )

    print(
        "Candidatos válidos:",
        len(candidates),
    )

    if candidates:

        print(
            "Principais candidatos:"
        )

        for candidate in candidates[
            :5
        ]:

            print(
                f"  score="
                f"{candidate['score']}"
                f" | "
                f"{candidate.get('text', '')}"
                f" | "
                f"{candidate['url']}"
            )

    # ========================================================
    # 7. TENTA CADA CANDIDATO
    # ========================================================

    for candidate in candidates[
        :MAX_CANDIDATES
    ]:

        pdf_url = (
            candidate["url"]
        )

        result = (
            try_candidate_download(
                context,
                pdf_url,
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