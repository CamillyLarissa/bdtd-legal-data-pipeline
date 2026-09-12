"""
Funções auxiliares para download de PDFs.

Este módulo não extrai metadados e não conhece a lógica da BDTD.

Responsabilidades:
- realizar requisições HTTP;
- validar se o conteúdo recebido é PDF;
- salvar PDFs;
- tentar download usando o contexto HTTP do Playwright.
"""

from pathlib import Path

import requests

from src.config import (
    MAX_RETRIES,
    REQUEST_TIMEOUT,
)


DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 "
        "(Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 "
        "(KHTML, like Gecko) "
        "Chrome/120 Safari/537.36"
    )
}

# Compatibilidade com versões anteriores do repository_parser
HEADERS = DEFAULT_HEADERS

def content_is_pdf(
    content: bytes,
    content_type: str | None = None,
) -> bool:
    """
    Verifica se o conteúdo recebido parece ser um PDF.

    São considerados:
    - assinatura %PDF;
    - Content-Type application/pdf.
    """
    if content.startswith(
        b"%PDF"
    ):
        return True

    content_type = (
        content_type
        or ""
    ).lower()

    return (
        "application/pdf"
        in content_type
    )


def save_pdf(
    content: bytes,
    destination: Path,
) -> bool:
    """
    Salva um PDF.

    Não sobrescreve arquivos válidos já existentes.
    """
    destination.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    if destination.exists():
        try:
            existing = (
                destination.read_bytes()[:4]
            )

            if existing == b"%PDF":
                return True
        except OSError:
            pass

    temporary = destination.with_suffix(
        destination.suffix + ".part"
    )

    try:
        with open(
            temporary,
            "wb",
        ) as file:
            file.write(content)

        temporary.replace(
            destination
        )

        return True

    except Exception:
        if temporary.exists():
            temporary.unlink(
                missing_ok=True
            )

        raise


def download_with_requests(
    url: str,
    destination: Path,
    session: requests.Session | None = None,
) -> bool:
    """
    Tenta baixar um PDF utilizando requests.
    """
    own_session = False

    if session is None:
        session = requests.Session()
        own_session = True

    session.headers.update(
        DEFAULT_HEADERS
    )

    try:
        for attempt in range(
            1,
            MAX_RETRIES + 1,
        ):
            try:
                response = session.get(
                    url,
                    timeout=REQUEST_TIMEOUT,
                    allow_redirects=True,
                )

                if response.status_code >= 400:
                    continue

                content_type = (
                    response.headers.get(
                        "Content-Type",
                        "",
                    )
                )

                if not content_is_pdf(
                    response.content,
                    content_type,
                ):
                    continue

                return save_pdf(
                    response.content,
                    destination,
                )

            except requests.RequestException:
                if (
                    attempt
                    >= MAX_RETRIES
                ):
                    return False

        return False

    finally:
        if own_session:
            session.close()


def download_with_browser_context(
    context,
    url: str,
    destination: Path,
) -> bool:
    """
    Tenta baixar o conteúdo usando a camada HTTP do contexto
    do Playwright.

    Isso pode ajudar quando o navegador já possui cookies
    obtidos durante a navegação normal.
    """
    try:
        response = (
            context.request.get(
                url,
                timeout=REQUEST_TIMEOUT
                * 1000,
            )
        )

        if not response.ok:
            return False

        content = response.body()

        content_type = (
            response.headers.get(
                "content-type",
                ""
            )
        )

        if not content_is_pdf(
            content,
            content_type,
        ):
            return False

        return save_pdf(
            content,
            destination,
        )

    except Exception:
        return False