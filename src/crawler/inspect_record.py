"""
Ferramenta de diagnóstico para visualizar um registro da BDTD.

Não faz parte do pipeline principal.
"""

import sys

from playwright.sync_api import sync_playwright

from src.config import (
    BDTD_HEADLESS,
    PAGE_TIMEOUT,
)


def inspect(
    record_url: str,
) -> None:
    """
    Abre um registro e imprime informações básicas.
    """
    with sync_playwright() as playwright:
        browser = (
            playwright.chromium.launch(
                headless=BDTD_HEADLESS,
            )
        )

        page = browser.new_page()

        page.goto(
            record_url,
            wait_until="domcontentloaded",
            timeout=PAGE_TIMEOUT,
        )

        page.wait_for_timeout(
            1000
        )

        print(
            "URL final:",
            page.url,
        )

        print(
            "Título HTML:",
            page.title(),
        )

        print(
            "\nTexto da página:"
        )

        body_text = (
            page.locator(
                "body"
            ).inner_text()
        )

        print(
            body_text[:5000]
        )

        browser.close()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(
            "Uso:"
        )

        print(
            "python -m "
            "src.crawler.inspect_record "
            "<URL_DO_REGISTRO>"
        )

        raise SystemExit(1)

    inspect(
        sys.argv[1]
    )