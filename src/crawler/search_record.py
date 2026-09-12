import json
import time
from pathlib import Path
from urllib.parse import urljoin, urlencode

from playwright.sync_api import sync_playwright


BASE_URL = "https://bdtd.ibict.br"
SEARCH_ENDPOINT = f"{BASE_URL}/vufind/Search/Results"

# Termo correspondente à área escolhida no trabalho
SEARCH_TERM = "Direito"

# Quantidade que queremos coletar para executar o pipeline
MAX_RECORDS = 100

# A BDTD está mostrando 20 registros por página
RESULTS_PER_PAGE = 20

OUTPUT_FILE = Path("data/raw/metadata/record_urls.json")


def build_search_url(page_number):
    """
    Monta a URL da pesquisa para uma determinada página.
    """

    params = {
        "lookfor": SEARCH_TERM,
        "type": "AllFields",
        "page": page_number,
    }

    return f"{SEARCH_ENDPOINT}?{urlencode(params)}"


def save_records(records):
    """
    Salva os links coletados em JSON.
    """

    OUTPUT_FILE.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    with open(
        OUTPUT_FILE,
        "w",
        encoding="utf-8",
    ) as file:
        json.dump(
            records,
            file,
            ensure_ascii=False,
            indent=2,
        )


def collect_record_links(page):
    """
    Coleta os links dos registros presentes
    na página atual da BDTD.
    """

    links = page.locator(
        "a[href*='/vufind/Record/']"
    )

    records = []

    for i in range(links.count()):
        href = links.nth(i).get_attribute("href")

        if not href:
            continue

        full_url = urljoin(
            BASE_URL,
            href,
        )

        if full_url not in records:
            records.append(full_url)

    return records


def crawl():
    """
    Percorre as páginas da pesquisa da BDTD
    até atingir MAX_RECORDS.
    """

    all_records = []

    with sync_playwright() as p:

        browser = p.chromium.launch(
            headless=False
        )

        page = browser.new_page()

        page_number = 1

        while len(all_records) < MAX_RECORDS:

            search_url = build_search_url(
                page_number
            )

            print("\n" + "=" * 60)
            print(f"Página {page_number}")
            print(f"URL: {search_url}")

            try:
                page.goto(
                    search_url,
                    wait_until="domcontentloaded",
                    timeout=60000,
                )

            except Exception as error:
                print(
                    f"Erro ao acessar página "
                    f"{page_number}: {error}"
                )
                break

            # Pequena espera para a BDTD terminar
            # de renderizar a página
            page.wait_for_timeout(3000)

            print(
                "Título:",
                page.title(),
            )

            page_records = collect_record_links(
                page
            )

            print(
                "Registros encontrados nesta página:",
                len(page_records),
            )

            # Se uma página não possuir mais registros,
            # consideramos que chegamos ao final.
            if not page_records:
                print(
                    "\nNenhum registro encontrado. "
                    "Encerrando."
                )
                break

            new_records = 0

            for record in page_records:

                if record not in all_records:

                    all_records.append(record)

                    new_records += 1

                    print(
                        f"[{len(all_records)}] "
                        f"{record}"
                    )

                    if len(all_records) >= MAX_RECORDS:
                        break

            # Salva a cada página.
            # Assim, se o programa parar no meio,
            # não perdemos o que já foi coletado.
            save_records(all_records)

            print(
                f"Novos registros desta página: "
                f"{new_records}"
            )

            print(
                f"Total acumulado: "
                f"{len(all_records)}"
            )

            # Proteção contra loop:
            # se mudar a página mas vier exatamente
            # o mesmo conteúdo, paramos.
            if new_records == 0:

                print(
                    "\nNenhum registro novo encontrado. "
                    "Possível fim da paginação."
                )

                break

            page_number += 1

            # Evita fazer requisições em sequência
            # muito rapidamente.
            time.sleep(1)

        browser.close()

    save_records(all_records)

    print("\n" + "=" * 60)
    print("COLETA FINALIZADA")
    print(
        f"Total coletado: "
        f"{len(all_records)}"
    )
    print(
        f"Arquivo salvo em: "
        f"{OUTPUT_FILE}"
    )


if __name__ == "__main__":
    crawl()