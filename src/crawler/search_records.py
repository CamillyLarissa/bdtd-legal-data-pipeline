"""
Coleta URLs de registros da BDTD a partir da busca por uma área/termo.

Esta etapa corresponde ao início da camada Raw do pipeline.

Fluxo:
    BDTD
      ↓
    página de resultados
      ↓
    URLs dos registros
      ↓
    data/raw/metadata/record_urls.json

A busca padrão utilizada no projeto é:
    lookfor=Direito
    type=AllFields
"""

import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode, urljoin

from playwright.sync_api import sync_playwright

from src.config import (
    BDTD_HEADLESS,
    BDTD_MAX_RECORDS,
    BDTD_QUERY,
    RECORD_URLS_FILE,
    create_directories,
)


BASE_URL = "https://bdtd.ibict.br"
SEARCH_URL = f"{BASE_URL}/vufind/Search/Results"


def build_search_url(query: str, page_number: int) -> str:
    """
    Monta a URL de busca da BDTD.

    Exemplo:
    https://bdtd.ibict.br/vufind/Search/Results
        ?lookfor=Direito
        &type=AllFields
        &page=1
    """
    params = {
    "lookfor": "",
    "type": "AllFields",
    "filter[]": (
        'dc.subject.cnpq.fl_str_mv:'
        '"CNPQ::CIENCIAS SOCIAIS APLICADAS::DIREITO"'
    ),
    "page": page_number,
    }

    return f"{SEARCH_URL}?{urlencode(params)}"


def extract_record_links(page) -> list[str]:
    """
    Extrai os links dos registros existentes na página atual.

    Em vez de depender de classes CSS específicas da interface,
    percorremos todos os links e selecionamos aqueles cujo href
    contém '/vufind/Record/'.

    Isso torna o crawler menos dependente da estrutura visual
    da página da BDTD.
    """
    links = page.locator("a")

    record_urls = []

    for index in range(links.count()):
        href = links.nth(index).get_attribute("href")

        if not href:
            continue

        if "/vufind/Record/" not in href:
            continue

        absolute_url = urljoin(BASE_URL, href)

        if absolute_url not in record_urls:
            record_urls.append(absolute_url)

    return record_urls


def save_record_urls(
    record_urls: list[str],
    output_file: Path,
) -> None:
    """
    Salva os registros coletados em JSON.
    """
    output_file.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    data = {
        "source": "BDTD",
        "query": BDTD_QUERY,
        "search_type": "AllFields",
        "collected_at": datetime.now(
            timezone.utc
        ).isoformat(),
        "total_collected": len(record_urls),
        "record_urls": record_urls,
    }

    with open(
        output_file,
        "w",
        encoding="utf-8",
    ) as file:
        json.dump(
            data,
            file,
            ensure_ascii=False,
            indent=2,
        )


def run() -> None:
    """
    Executa a busca na BDTD até atingir BDTD_MAX_RECORDS.

    O processo percorre as páginas de resultados e acumula
    URLs únicas de registros.
    """
    create_directories()

    print(f"Consulta: {BDTD_QUERY}")
    print(f"Limite: {BDTD_MAX_RECORDS}")
    print()

    collected_urls = []
    seen_urls = set()

    page_number = 1

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=BDTD_HEADLESS,
        )

        context = browser.new_context(
            viewport={
                "width": 1440,
                "height": 900,
            }
        )

        page = context.new_page()

        while len(collected_urls) < BDTD_MAX_RECORDS:
            current_url = build_search_url(
                BDTD_QUERY,
                page_number,
            )

            print(f"Página {page_number}")
            print(current_url)

            try:
                page.goto(
                    current_url,
                    wait_until="domcontentloaded",
                    timeout=60000,
                )

                # Dá tempo para os resultados terminarem de aparecer.
                page.wait_for_timeout(3000)

            except Exception as error:
                print(
                    f"Erro ao abrir página {page_number}: "
                    f"{error}"
                )
                break

            print(
                "Título:",
                page.title(),
            )

            page_record_urls = extract_record_links(
                page
            )

            print(
                "Encontrados na página:",
                len(page_record_urls),
            )

            new_records = 0

            for record_url in page_record_urls:
                if record_url in seen_urls:
                    continue

                seen_urls.add(record_url)
                collected_urls.append(record_url)

                new_records += 1

                if (
                    len(collected_urls)
                    >= BDTD_MAX_RECORDS
                ):
                    break

            print(
                "Novos:",
                new_records,
            )

            print(
                "Total coletado:",
                len(collected_urls),
            )

            print()

            if not page_record_urls:
                print(
                    "Nenhum registro encontrado "
                    "na página."
                )
                break

            if new_records == 0:
                print(
                    "Nenhum registro novo encontrado. "
                    "Encerrando para evitar loop."
                )
                break

            page_number += 1

        context.close()
        browser.close()

    # Respeita exatamente o limite solicitado.
    collected_urls = collected_urls[
        :BDTD_MAX_RECORDS
    ]

    save_record_urls(
        collected_urls,
        RECORD_URLS_FILE,
    )

    print()
    print("Busca finalizada.")
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