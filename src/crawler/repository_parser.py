"""
Descoberta e download de PDFs nos repositórios institucionais.

Responsabilidades:
- abrir páginas dos repositórios;
- resolver URLs Handle quando possível;
- consultar DSpace moderno;
- descobrir links candidatos;
- priorizar links de download;
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
# CONFIGURAÇÕES
# ============================================================

MAX_CANDIDATES = 20


# ============================================================
# RESOLUÇÃO DE HANDLE
# ============================================================

def resolve_handle_urls(
    repository_url,
):
    """
    Gera possíveis URLs alternativas para identificadores Handle.

    Exemplo:

        http://hdl.handle.net/11612/7938

    Pode resolver para o repositório institucional atual.

    O endereço original nunca é descartado.
    """

    if not repository_url:
        return []

    repository_url = (
        str(repository_url)
        .strip()
    )

    urls = []

    parsed = urlparse(
        repository_url
    )

    host = (
        parsed.netloc
        .lower()
    )

    # --------------------------------------------------------
    # NÃO É HANDLE
    # --------------------------------------------------------

    if (
        "hdl.handle.net"
        not in host
    ):
        return [
            repository_url
        ]

    print(
        "Identificador Handle detectado:"
    )

    print(
        repository_url
    )

    # --------------------------------------------------------
    # 1. TENTA RESOLVER PELO SERVIÇO HANDLE
    # --------------------------------------------------------

    try:
        response = requests.get(
            repository_url,
            headers=HEADERS,
            timeout=REQUEST_TIMEOUT,
            verify=False,
            allow_redirects=True,
        )

        final_url = (
            response.url
            if response.url
            else None
        )

        if final_url:

            final_host = (
                urlparse(
                    final_url
                )
                .netloc
                .lower()
            )

            if (
                "hdl.handle.net"
                not in final_host
            ):

                print(
                    "Handle resolvido para:"
                )

                print(
                    final_url
                )

                urls.append(
                    final_url
                )

    except Exception as error:

        print(
            "Falha ao resolver Handle:"
        )

        print(
            error
        )

    # --------------------------------------------------------
    # 2. FALLBACK UFT
    #
    # prefixo Handle:
    #
    #     11612
    #
    # exemplo:
    #
    # http://hdl.handle.net/11612/7938
    #
    # ->
    #
    # https://umbu.uft.edu.br/handle/11612/7938
    # --------------------------------------------------------

    handle_path = (
        parsed.path
        .strip("/")
    )

    if handle_path.startswith(
        "11612/"
    ):

        fallback_uft = (
            "https://umbu.uft.edu.br/"
            f"handle/{handle_path}"
        )

        if fallback_uft not in urls:

            print(
                "Fallback UFT:"
            )

            print(
                fallback_uft
            )

            urls.append(
                fallback_uft
            )

    # --------------------------------------------------------
    # 3. URL ORIGINAL
    # --------------------------------------------------------

    if repository_url not in urls:

        urls.append(
            repository_url
        )

    return urls


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

    item_uuid = (
        match.group(1)
    )

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
                bundle.get(
                    "uuid"
                )
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
                    f"{base}"
                    f"/server/api/core/"
                    f"bitstreams/"
                    f"{bitstream_uuid}"
                    f"/content"
                )

                print(
                    "PDF encontrado pela "
                    "API DSpace:"
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
            "DSpace API falhou:"
        )

        print(
            error
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
    Dá prioridade a padrões comuns de arquivos
    em DSpace, TEDE e outros repositórios.
    """

    score = 0

    lower_url = (
        str(url)
        .lower()
        .strip()
    )

    lower_text = (
        str(text)
        .lower()
        .strip()
    )

    # --------------------------------------------------------
    # TEXTO DO LINK/BOTÃO
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
        marker in lower_text
        for marker in download_markers
    ):
        score += 120

    # --------------------------------------------------------
    # PADRÕES DE URL
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

    return score


# ============================================================
# COLETA DE CANDIDATOS POR LINKS
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
            count = (
                locator.count()
            )

        except Exception:
            continue

        for index in range(
            count
        ):

            element = (
                locator.nth(
                    index
                )
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

            # Ignora links que não levam a arquivo/página.
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
                    element
                    .inner_text()
                    .strip()
                )

            except Exception:
                text = ""

            # Pontuação já existente no projeto.
            try:
                base_score = (
                    score_candidate(
                        url,
                        text,
                    )
                )

            except Exception:
                base_score = 0

            # Pontuação complementar.
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
# COLETA DE CANDIDATOS PELO HTML
# ============================================================

def collect_candidates_from_html(
    page,
):
    """
    Procura URLs candidatas diretamente
    no HTML da página.

    Isso ajuda quando o link do arquivo aparece
    dentro de scripts ou atributos.
    """

    try:
        html = (
            page.content()
        )

    except Exception:
        return []

    candidates = []

    patterns = [
        # ----------------------------------------------------
        # PDF absoluto
        # ----------------------------------------------------
        (
            r'https?://'
            r'[^"\'<>\s]+'
            r'\.pdf'
            r'(?:\?[^"\'<>\s]*)?'
        ),

        # ----------------------------------------------------
        # Bitstream
        # ----------------------------------------------------
        (
            r'["\']'
            r'([^"\']*/bitstream/'
            r'[^"\']+)'
            r'["\']'
        ),

        # ----------------------------------------------------
        # Bitstreams / download
        # ----------------------------------------------------
        (
            r'["\']'
            r'([^"\']*/bitstreams/'
            r'[^"\']+/download'
            r'[^"\']*)'
            r'["\']'
        ),

        # ----------------------------------------------------
        # DSpace REST
        # ----------------------------------------------------
        (
            r'["\']'
            r'([^"\']*/server/api/core/'
            r'bitstreams/'
            r'[^"\']+/content)'
            r'["\']'
        ),

        # ----------------------------------------------------
        # Retrieve
        # ----------------------------------------------------
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
                match = (
                    match[0]
                )

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
# FILTRAGEM E ORDENAÇÃO
# ============================================================

def find_pdf_candidates(
    page,
):
    """
    Combina candidatos encontrados no DOM
    e no HTML.

    Remove duplicatas e ordena por pontuação.
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

        # ----------------------------------------------------
        # VALIDAÇÃO NORMAL
        # ----------------------------------------------------

        try:
            valid = (
                valid_candidate_url(
                    url
                )
            )

        except Exception:
            valid = False

        # ----------------------------------------------------
        # CANDIDATO FORTE
        #
        # Permite links como "Baixar/Abrir" mesmo que
        # valid_candidate_url() não os reconheça.
        # ----------------------------------------------------

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
            not valid
            and not strong_candidate
        ):
            continue

        seen.add(
            url
        )

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
    Abre página do repositório utilizando Playwright.

    Faz várias tentativas antes de desistir.
    """

    for attempt in range(
        1,
        MAX_RETRIES + 1,
    ):

        try:
            print(
                f"Abrindo repositório "
                f"(tentativa {attempt}/"
                f"{MAX_RETRIES})"
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
                "Falha ao abrir:"
            )

            print(
                error
            )

            if (
                attempt
                < MAX_RETRIES
            ):

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
    Tenta baixar um candidato usando:

    1. requests;
    2. contexto Playwright.
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
        # 1. REQUESTS
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
        # 2. PLAYWRIGHT
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
        "reason": (
            "candidate_failed"
        ),
    }


# ============================================================
# PROCESSA UMA PÁGINA DO REPOSITÓRIO
# ============================================================

def process_repository_page(
    page,
    context,
    repository_url,
    output_file,
):
    """
    Processa uma URL já resolvida.

    Essa função:
    - testa PDF direto;
    - testa DSpace moderno;
    - abre a página;
    - procura candidatos;
    - tenta baixar.
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
    # 2. DSPACE MODERNO
    # ========================================================

    if "/items/" in repository_url:

        result = (
            try_dspace_item_api(
                repository_url,
                output_file,
            )
        )

        if result["success"]:
            return result

    # ========================================================
    # 3. ABRE REPOSITÓRIO
    # ========================================================

    opened = (
        open_repository(
            page,
            repository_url,
        )
    )

    # --------------------------------------------------------
    # Alguns repositórios antigos funcionam melhor em HTTPS.
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

        opened = (
            open_repository(
                page,
                https_url,
            )
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

    special = (
        detect_special_page(
            page
        )
    )

    if special:

        return {
            "success": False,
            "reason": special,
        }

    # ========================================================
    # 5. DSPACE MODERNO APÓS REDIRECIONAMENTO
    # ========================================================

    if "/items/" in page.url:

        result = (
            try_dspace_item_api(
                page.url,
                output_file,
            )
        )

        if result["success"]:
            return result

    # ========================================================
    # 6. CANDIDATOS
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

    # --------------------------------------------------------
    # Exibe os principais candidatos para diagnóstico.
    # --------------------------------------------------------

    if candidates:

        print(
            "Principais candidatos:"
        )

        for candidate in (
            candidates[:5]
        ):

            print(
                "  "
                f"score={candidate['score']}"
                " | "
                f"{candidate.get('text', '')}"
                " | "
                f"{candidate['url']}"
            )

    # ========================================================
    # 7. DOWNLOAD
    # ========================================================

    for candidate in (
        candidates[
            :MAX_CANDIDATES
        ]
    ):

        result = (
            try_candidate_download(
                context,
                candidate["url"],
                output_file,
                referer=page.url,
            )
        )

        if result["success"]:
            return result

    return {
        "success": False,
        "reason": (
            "pdf_not_found"
        ),
    }


# ============================================================
# FUNÇÃO PRINCIPAL USADA PELO DOWNLOADER
# ============================================================

def process_repository_url(
    page,
    context,
    repository_url,
    output_file,
):
    """
    Processa uma URL externa fornecida pela BDTD.

    Se for Handle:
    - tenta resolver;
    - tenta fallback conhecido;
    - tenta URL original.

    Depois procura o PDF correspondente.

    Este é o contrato principal utilizado pelo
    downloader.py.
    """

    repository_url = (
        str(repository_url)
        .strip()
    )

    print(
        "URL recebida:"
    )

    print(
        repository_url
    )

    # ========================================================
    # RESOLVE POSSÍVEIS ALTERNATIVAS
    # ========================================================

    resolved_urls = (
        resolve_handle_urls(
            repository_url
        )
    )

    print(
        "URLs candidatas de repositório:",
        len(resolved_urls),
    )

    for candidate_url in (
        resolved_urls
    ):

        print()
        print(
            "-" * 60
        )

        print(
            "Tentando repositório:"
        )

        print(
            candidate_url
        )

        result = (
            process_repository_page(
                page,
                context,
                candidate_url,
                output_file,
            )
        )

        if result["success"]:

            if (
                "url"
                not in result
            ):
                result["url"] = (
                    candidate_url
                )

            return result

        reason = (
            result.get(
                "reason",
                "unknown",
            )
        )

        print(
            "Falha desta URL:",
            reason
        )

        # ----------------------------------------------------
        # Não tenta contornar restrições reais.
        # ----------------------------------------------------

        if reason in {
            "restricted_or_embargo",
            "anti_bot",
        }:

            return result

    return {
        "success": False,
        "reason": (
            "pdf_not_found"
        ),
    }