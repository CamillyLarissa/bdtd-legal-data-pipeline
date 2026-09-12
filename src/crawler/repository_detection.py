"""
Detecção e classificação de páginas e URLs de repositórios.

Responsabilidades:
- eliminar falsas URLs;
- atribuir prioridade aos candidatos de PDF;
- identificar páginas com embargo/restrição;
- identificar páginas protegidas por mecanismos anti-bot;
- identificar páginas indisponíveis.

Este módulo apenas classifica.
Ele não realiza downloads.
"""


# ============================================================
# FILTRO DE URLs FALSAS
# ============================================================

INVALID_FRAGMENTS = [
    "bitstream.download.page",
    "bitstream-request-a-copy",
    "file-download-link",
    "item.edit.bitstreams",
    "item.page.filesection",
    "statistics.table",
    "submission.sections",
    "follow restricted download",
    "request-copy",
    "secure-access",
    "candownload1",
    "candownload2",
]


def valid_candidate_url(url):
    """
    Verifica se uma URL pode ser considerada
    candidata real a um PDF.

    O filtro também remove strings internas de
    interfaces DSpace que poderiam ser
    interpretadas incorretamente como links.
    """

    if not url:
        return False

    lower = url.lower()

    if lower.startswith(
        (
            "mailto:",
            "javascript:",
            "tel:",
        )
    ):
        return False

    for fragment in INVALID_FRAGMENTS:
        if fragment in lower:
            return False

    invalid_chars = [
        "<",
        ">",
        "<!---->",
        "</",
        "class=",
    ]

    for fragment in invalid_chars:
        if fragment in lower:
            return False

    # Evita strings muito grandes geradas por
    # capturas incorretas de HTML.
    if len(url) > 1000:
        return False

    return True


# ============================================================
# PONTUAÇÃO DE CANDIDATOS
# ============================================================


def score_candidate(
    url,
    text="",
):
    """
    Atribui pontuação a uma URL de acordo com
    indícios de que ela representa um PDF.

    Quanto maior a pontuação, maior a prioridade.
    """

    if not valid_candidate_url(url):
        return -100

    lower_url = url.lower()

    lower_text = (
        text.lower()
        if text
        else ""
    )

    score = 0

    if ".pdf" in lower_url:
        score += 50

    if "/bitstream/" in lower_url:
        score += 35

    if "/bitstreams/" in lower_url:
        score += 35

    if (
        "/server/api/core/bitstreams/"
        in lower_url
    ):
        score += 40

    if "/content" in lower_url:
        score += 15

    if "/download" in lower_url:
        score += 15

    if "pdf" in lower_text:
        score += 15

    if "baixar" in lower_text:
        score += 10

    if "download" in lower_text:
        score += 10

    if "texto completo" in lower_text:
        score += 10

    if "visualizar" in lower_text:
        score += 5

    if "abrir" in lower_text:
        score += 5

    return score


# ============================================================
# DETECÇÃO DE PÁGINAS ESPECIAIS
# ============================================================


def detect_special_page(page):
    """
    Identifica páginas que não devem continuar
    pelo fluxo normal.

    Possíveis resultados:

        anti_bot
        restricted_or_embargo
        repository_unavailable
        not_found

    Retorna None quando nada especial é detectado.
    """

    try:
        title = page.title().lower()

    except Exception:
        title = ""

    try:
        body = (
            page.locator("body")
            .inner_text(
                timeout=5000
            )
            .lower()
        )

    except Exception:
        body = ""

    content = (
        title
        + "\n"
        + body
    )

    # --------------------------------------------------------
    # Anti-bot / validação de segurança
    # --------------------------------------------------------

    anti_bot_terms = [
        "client verifying",
        "checking your browser",
        "safeline waf",
        "verificando conexão",
        "verificando conexao",
        "um momento…",
        "um momento...",

        # UFSC - Sistema de Prevenção de Ataques
        "sistema de prevenção de ataques da redeufsc",
        "sistema de prevencao de ataques da redeufsc",
        "por motivos de segurança, esta validação será solicitada",
        "por motivos de seguranca, esta validacao sera solicitada",
        "acesso ao site seja de fora da redeufsc",
        "acesso ao site seja de fora da rede ufsc",
        "redeufsc",
    ]

    for term in anti_bot_terms:
        if term in content:
            return "anti_bot"

    # --------------------------------------------------------
    # Acesso restrito ou embargo
    # --------------------------------------------------------

    restriction_terms = [
        "tipo de acesso: acesso embargado",
        "acesso embargado",
        "restricted access",
        "arquivo restrito",
        "acesso restrito",
    ]

    for term in restriction_terms:
        if term in content:
            return (
                "restricted_or_embargo"
            )

    # --------------------------------------------------------
    # Repositório indisponível
    # --------------------------------------------------------

    unavailable_terms = [
        "cannot connect to server",
        "service unavailable",
    ]

    for term in unavailable_terms:
        if term in content:
            return (
                "repository_unavailable"
            )

    # --------------------------------------------------------
    # Não encontrado
    # --------------------------------------------------------

    not_found_terms = [
        "page not found",
        "404 not found",
        "página não encontrada",
        "pagina nao encontrada",
    ]

    for term in not_found_terms:
        if term in content:
            return "not_found"

    return None