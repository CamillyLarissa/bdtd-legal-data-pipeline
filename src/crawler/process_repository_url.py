"""
Descoberta de PDFs nos repositórios institucionais.

A BDTD funciona como agregadora. O documento completo geralmente
está hospedado no repositório da universidade.

Este módulo tenta localizar o PDF público sem contornar:
- CAPTCHA;
- WAF;
- anti-bot;
- documentos embargados;
- documentos de acesso restrito.
"""

import re
from urllib.parse import urljoin

import requests

from src.crawler.download_utils import (
    download_with_browser_context,
    download_with_requests,
)
from src.config import (
    PAGE_TIMEOUT,
    PDF_DIR,
)


INVALID_CANDIDATE_FRAGMENTS = [
    "bitstream-request-a-copy",
    "file-download-link",
    "item.edit.bitstreams",
    "item.page.filesection",
    "statistics.table",
    "submission.sections",
]


def result(
    *,
    success: bool,
    reason: str | None,
    source_url: str | None,
    pdf_url: str | None,
    path: str | None,
) -> dict:
    """
    Padroniza o retorno do parser.
    """
    return {
        "success": success,
        "reason": reason,
        "source_url": source_url,
        "pdf_url": pdf_url,
        "path": path,
    }


def is_invalid_candidate(
    url: str,
) -> bool:
    """
    Rejeita strings internas e links de interface que não
    representam arquivos.
    """
    lowered = url.lower()

    return any(
        fragment in lowered
        for fragment in
        INVALID_CANDIDATE_FRAGMENTS
    )


def score_candidate(
    url: str,
) -> int:
    """
    Atribui prioridade a URLs que parecem representar PDFs.
    """
    if not url:
        return -100

    if is_invalid_candidate(url):
        return -100

    lowered = url.lower()

    score = 0

    if ".pdf" in lowered:
        score += 50

    if "/bitstream/" in lowered:
        score += 30

    if "/bitstreams/" in lowered:
        score += 30

    if "/download" in lowered:
        score += 15

    if "/content" in lowered:
        score += 15

    return score


def detect_special_page(
    body_text: str,
) -> str | None:
    """
    Detecta situações em que o crawler não deve tentar
    contornar o acesso.
    """
    text = body_text.lower()

    restricted_phrases = [
        "tipo de acesso: acesso embargado",
        "acesso embargado",
        "restricted access",
        "arquivo restrito",
        "acesso restrito",
    ]

    if any(
        phrase in text
        for phrase in restricted_phrases
    ):
        return (
            "restricted_or_embargo"
        )

    anti_bot_phrases = [
        "client verifying",
        "checking your browser",
        "verify you are human",
        "verificando conexão",
        "captcha",
    ]

    if any(
        phrase in text
        for phrase in anti_bot_phrases
    ):
        return "anti_bot"

    return None


def collect_candidates(
    page,
    base_url: str,
) -> list[str]:
    """
    Coleta URLs potencialmente relacionadas ao PDF.
    """
    candidates: set[str] = set()

    selectors = [
        ("a[href]", "href"),
        ("iframe[src]", "src"),
        ("embed[src]", "src"),
        ("object[data]", "data"),
    ]

    for selector, attribute in selectors:
        elements = page.locator(
            selector
        )

        for index in range(
            elements.count()
        ):
            value = elements.nth(
                index
            ).get_attribute(
                attribute
            )

            if not value:
                continue

            absolute = urljoin(
                base_url,
                value,
            )

            if (
                score_candidate(
                    absolute
                )
                <= 0
            ):
                continue

            candidates.add(
                absolute
            )

    return sorted(
        candidates,
        key=score_candidate,
        reverse=True,
    )


def try_direct_pdf(
    url: str,
    destination,
    session,
    context,
) -> bool:
    """
    Testa uma URL candidata usando requests e, se necessário,
    o contexto Playwright.
    """
    if download_with_requests(
        url,
        destination,
        session=session,
    ):
        return True

    if context is not None:
        if download_with_browser_context(
            context,
            url,
            destination,
        ):
            return True

    return False


def process_repository_url(
    source_url: str,
    record_id: str,
    page,
    session: requests.Session,
) -> dict:
    """
    Processa uma URL externa de repositório e tenta localizar
    o PDF público correspondente.

    Retorna sempre um dicionário padronizado.
    """
    destination = (
        PDF_DIR
        / f"{record_id}.pdf"
    )

    # Não sobrescreve documentos existentes.
    if destination.exists():
        return result(
            success=True,
            reason="already_exists",
            source_url=source_url,
            pdf_url=None,
            path=str(destination),
        )

    # --------------------------------------------------------
    # Estratégia 1: a própria URL pode ser um PDF.
    # --------------------------------------------------------

    if ".pdf" in source_url.lower():
        if try_direct_pdf(
            source_url,
            destination,
            session,
            page.context,
        ):
            return result(
                success=True,
                reason=None,
                source_url=source_url,
                pdf_url=source_url,
                path=str(destination),
            )

    # --------------------------------------------------------
    # Estratégia 2: abrir página do repositório.
    # --------------------------------------------------------

    try:
        page.goto(
            source_url,
            wait_until="domcontentloaded",
            timeout=PAGE_TIMEOUT,
        )

        page.wait_for_timeout(
            1000
        )

    except Exception:
        return result(
            success=False,
            reason="repository_unavailable",
            source_url=source_url,
            pdf_url=None,
            path=None,
        )

    try:
        body_text = (
            page.locator(
                "body"
            ).inner_text()
        )
    except Exception:
        body_text = ""

    special_reason = (
        detect_special_page(
            body_text
        )
    )

    if special_reason:
        return result(
            success=False,
            reason=special_reason,
            source_url=source_url,
            pdf_url=None,
            path=None,
        )

    # --------------------------------------------------------
    # Estratégia 3: localizar links PDF/bitstream.
    # --------------------------------------------------------

    candidates = (
        collect_candidates(
            page,
            page.url,
        )
    )

    for candidate in candidates:
        if try_direct_pdf(
            candidate,
            destination,
            session,
            page.context,
        ):
            return result(
                success=True,
                reason=None,
                source_url=source_url,
                pdf_url=candidate,
                path=str(destination),
            )

    return result(
        success=False,
        reason="pdf_not_found",
        source_url=source_url,
        pdf_url=None,
        path=None,
    )