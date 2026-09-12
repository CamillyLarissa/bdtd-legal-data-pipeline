"""
Utilidades para download de arquivos PDF.

Responsabilidades:
- configuração HTTP;
- validação de conteúdo PDF;
- geração de URLs alternativas;
- download usando requests;
- download usando o contexto do Playwright.

Este módulo NÃO decide qual PDF pertence ao registro.
Essa responsabilidade pertence ao repository_parser.py.
"""

import os
import time
from pathlib import Path

import requests
import urllib3


# ============================================================
# CONFIGURAÇÕES
# ============================================================

REQUEST_TIMEOUT = 20
PAGE_TIMEOUT = 30000

MAX_RETRIES = 2
RETRY_WAIT_SECONDS = 3


urllib3.disable_warnings(
    urllib3.exceptions.InsecureRequestWarning
)


HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 "
        "(Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 "
        "(KHTML, like Gecko) "
        "Chrome/152.0.0.0 "
        "Safari/537.36"
    ),
    "Accept": (
        "text/html,"
        "application/xhtml+xml,"
        "application/xml;q=0.9,"
        "application/pdf;q=0.8,"
        "*/*;q=0.7"
    ),
}


# ============================================================
# URLs
# ============================================================


def alternative_urls(url):
    """
    Retorna a URL original e, quando aplicável,
    uma alternativa HTTPS.

    Exemplo:

        http://repositorio.exemplo/arquivo.pdf

    gera:

        [
            "http://repositorio.exemplo/arquivo.pdf",
            "https://repositorio.exemplo/arquivo.pdf",
        ]
    """

    urls = [url]

    if url.startswith("http://"):
        https_url = (
            "https://"
            + url[len("http://"):]
        )

        urls.append(https_url)

    return list(
        dict.fromkeys(urls)
    )


def is_direct_pdf_url(url):
    """
    Verifica se a URL termina diretamente em .pdf.
    """

    clean = (
        url.lower()
        .split("?")[0]
        .split("#")[0]
    )

    return clean.endswith(".pdf")


# ============================================================
# VALIDAÇÃO DE PDF
# ============================================================


def content_is_pdf_bytes(
    content,
    content_type="",
):
    """
    Verifica se o conteúdo recebido realmente é PDF.

    A validação utiliza:
    - Content-Type application/pdf;
    - assinatura binária %PDF.
    """

    content_type = (
        content_type or ""
    ).lower()

    return (
        "application/pdf"
        in content_type
        or content.startswith(b"%PDF")
    )


# ============================================================
# DOWNLOAD COM REQUESTS
# ============================================================


def download_with_requests(
    url,
    output_file,
    referer=None,
):
    """
    Tenta baixar um PDF utilizando requests.

    Args:
        url:
            URL candidata ao PDF.

        output_file:
            Path onde o PDF será salvo.

        referer:
            Página de origem, quando necessária.

    Returns:
        dict com:
            success
            url ou reason
    """

    headers = HEADERS.copy()

    if referer:
        headers["Referer"] = referer

    for attempt in range(
        1,
        MAX_RETRIES + 1,
    ):
        try:

            response = requests.get(
                url,
                headers=headers,
                timeout=REQUEST_TIMEOUT,
                allow_redirects=True,
                verify=False,
            )

            if response.status_code == 429:

                time.sleep(
                    RETRY_WAIT_SECONDS
                    * attempt
                )

                continue

            response.raise_for_status()

            content_type = (
                response.headers.get(
                    "Content-Type",
                    "",
                )
            )

            if not content_is_pdf_bytes(
                response.content,
                content_type,
            ):
                return {
                    "success": False,
                    "reason": "not_pdf",
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
            }

        except Exception as error:

            print(
                f"Erro de download: "
                f"{error}"
            )

            if attempt < MAX_RETRIES:

                time.sleep(
                    RETRY_WAIT_SECONDS
                    * attempt
                )

    return {
        "success": False,
        "reason": "request_failed",
    }


# ============================================================
# DOWNLOAD COM PLAYWRIGHT
# ============================================================


def download_with_browser_context(
    context,
    url,
    output_file,
    referer=None,
):
    """
    Tenta baixar o PDF usando o contexto HTTP
    do navegador Playwright.

    É usado como fallback quando requests não
    consegue acessar o arquivo.
    """

    try:

        headers = {}

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
            }

        body = response.body()

        content_type = (
            response.headers.get(
                "content-type",
                "",
            )
        )

        if not content_is_pdf_bytes(
            body,
            content_type,
        ):
            return {
                "success": False,
                "reason": "not_pdf",
            }

        output_file.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        output_file.write_bytes(body)

        return {
            "success": True,
            "url": url,
        }

    except Exception as error:

        print(
            "Browser context falhou:",
            error,
        )

        return {
            "success": False,
            "reason": (
                "browser_context_failed"
            ),
        }