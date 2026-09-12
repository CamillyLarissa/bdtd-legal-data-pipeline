"""
Busca registros na BDTD.

A consulta padrão utiliza:

    lookfor=Direito
    type=AllFields

Os links encontrados são armazenados em:

    data/raw/metadata/record_urls.json

ou no diretório definido pela variável BDTD_DATA_DIR.
"""

import json
from datetime import datetime, timezone
from urllib.parse import urlencode

from playwright.sync_api import sync_playwright

from src.config import (
    BDTD_HEADLESS,
    BDTD_MAX_RECORDS,
    BDTD_QUERY,
    PAGE_TIMEOUT,
    RECORD_URLS_FILE,
    create_directories,
)


BASE_SEARCH_URL = (
    "https://bdtd.ibict.br/vufind/Search/Results"
)


def build_search_url(
    query: str,
    page_number: int,
) -> str:
    """
    Cria a URL de busca da BDTD.
    """
    params = {
        "lookfor": query,
        "type": "AllFields",
        "page": page_number,
    }

    return (
        f"{BASE_SEARCH_URL}?"
        f"{urlencode(params)}"
    )


def normalize_record_url(
    href: str,
) -> str | None:
    """
    Converte links relativos de registros em URLs absolutas.
    """
    if not href:
        return None

    if "/vufind/Record/" not in href:
        return None

    if href.startswith("http://") or href.startswith("https://"):
        return href

    if href.startswith("/"):
        return (
            "https://bdtd.ibict.br"
            + href
        )

    return (
        "https://bdtd.ibict.br/"
        + href.lstrip("/")
    )


def save_record_urls(
    urls: list[str],
) -> None:
    """
    Salva as URLs coletadas.

    Não utiliza arquivo .tmp como entrada posteriormente.
    """
    RECORD_URLS_FILE.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    payload = {
        "source": "BDTD",
        "query": BDTD_QUERY,
        "search_type": "AllFields",
        "collected_at": (
            datetime.now(timezone.utc)
            .isoformat()
        ),
        "total_collected": len(urls),
        "record_urls": urls,
    }

    with open(
        RECORD_URLS_FILE,
        "w",
        encoding="utf-8",
    ) as file:
        json.dump(
            payload,
            file,
            ensure_ascii=False,
            indent=2,
        )


def run() -> None:
    """
    Executa a busca paginada da BDTD.
    """
    create_directories()

    collected_urls: list[str] = []
    collected_set: set[str] = set()

    print(f"Consulta: {BDTD_QUERY}")
    print(
        f"Limite: {BDTD_MAX_RECORDS}"
    )

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=BDTD_HEADLESS,
        )

        page = browser.new_page()

        page.set_default_timeout(
            PAGE_TIMEOUT,
        )

        page_number = 1

        while (
            len(collected_urls)
            < BDTD_MAX_RECORDS
        ):
            url = build_search_url(
                BDTD_QUERY,
                page_number,
            )

            print(
                f"\nPágina {page_number}"
            )
            print(url)

            try:
                page.goto(
                    url,
                    wait_until="domcontentloaded",
                    timeout=PAGE_TIMEOUT,
                )

                page.wait_for_timeout(1500)

            except Exception as error:
                print(
                    "Erro ao abrir página:",
                    error,
                )

                break

            anchors = page.locator(
                'a[href*="/vufind/Record/"]'
            )

            count = anchors.count()

            new_on_page = 0

            for index in range(count):
                href = anchors.nth(
                    index
                ).get_attribute("href")

                record_url = (
                    normalize_record_url(
                        href
                    )
                )

                if not record_url:
                    continue

                if record_url in collected_set:
                    continue

                collected_set.add(
                    record_url
                )

                collected_urls.append(
                    record_url
                )

                new_on_page += 1

                if (
                    len(collected_urls)
                    >= BDTD_MAX_RECORDS
                ):
                    break

            print(
                f"Encontrados na página: {count}"
            )
            print(
                f"Novos: {new_on_page}"
            )
            print(
                f"Total coletado: "
                f"{len(collected_urls)}"
            )

            if count == 0:
                print(
                    "Nenhum registro encontrado "
                    "na página."
                )
                break

            if new_on_page == 0:
                print(
                    "Nenhum registro novo. "
                    "Encerrando paginação."
                )
                break

            page_number += 1

        browser.close()

    save_record_urls(
        collected_urls[
            :BDTD_MAX_RECORDS
        ]
    )

    print("\nBusca finalizada.")
    print(
        "Registros:",
        len(collected_urls),
    )
    print(
        "Arquivo:",
        RECORD_URLS_FILE,
    )


if __name__ == "__main__":
    run()