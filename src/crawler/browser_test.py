"""
Teste simples para verificar se o Playwright consegue abrir a BDTD.

Não faz parte do pipeline principal.
"""

from playwright.sync_api import sync_playwright

from src.config import (
    BDTD_HEADLESS,
    PAGE_TIMEOUT,
)


URL = (
    "https://bdtd.ibict.br/vufind/"
)


def run() -> None:
    with sync_playwright() as playwright:
        browser = (
            playwright.chromium.launch(
                headless=BDTD_HEADLESS,
            )
        )

        page = browser.new_page()

        page.goto(
            URL,
            wait_until="domcontentloaded",
            timeout=PAGE_TIMEOUT,
        )

        page.wait_for_timeout(
            1500
        )

        print(
            "URL:",
            page.url,
        )

        print(
            "Título:",
            page.title(),
        )

        browser.close()


if __name__ == "__main__":
    run()