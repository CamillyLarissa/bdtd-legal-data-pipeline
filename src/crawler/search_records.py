import json
import os
import random
import time
from pathlib import Path
from urllib.parse import urlencode

from playwright.sync_api import sync_playwright
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError


# ============================================================
# CONFIGURAÇÕES
# ============================================================

BASE_URL = "https://bdtd.ibict.br/vufind/Search/Results"

DATA_DIR = Path(
    os.getenv(
        "BDTD_DATA_DIR",
        "data"
    )
)

MAX_RECORDS = int(
    os.getenv(
        "BDTD_MAX_RECORDS",
        "2500"
    )
)

HEADLESS = (
    os.getenv(
        "BDTD_HEADLESS",
        "true"
    ).lower()
    == "true"
)

METADATA_DIR = (
    DATA_DIR
    / "raw"
    / "metadata"
)

RECORD_URLS_FILE = (
    METADATA_DIR
    / "record_urls.json"
)

MAX_RETRIES_PER_PAGE = 8

RETRY_WAIT_SECONDS = 30

MIN_PAGE_DELAY = 1.5
MAX_PAGE_DELAY = 3.0


# ============================================================
# FILTRO CNPQ DE DIREITO
# ============================================================

CNPQ_FILTER = (
    'dc.subject.cnpq.fl_str_mv:'
    '"CNPQ::CIENCIAS SOCIAIS APLICADAS::DIREITO"'
)


# ============================================================
# ANOS
# ============================================================

START_YEAR = int(
    os.getenv(
        "BDTD_START_YEAR",
        "2026"
    )
)

END_YEAR = int(
    os.getenv(
        "BDTD_END_YEAR",
        "1990"
    )
)

YEARS = list(
    range(
        START_YEAR,
        END_YEAR - 1,
        -1
    )
)


# ============================================================
# DIRETÓRIOS
# ============================================================

def create_directories():
    METADATA_DIR.mkdir(
        parents=True,
        exist_ok=True
    )


# ============================================================
# URL DE BUSCA
# ============================================================

def build_search_url(
    page_number,
    year
):
    """
    Busca documentos da área Direito
    em um determinado ano.

    A divisão por ano evita depender de uma única
    consulta com paginação limitada.
    """

    params = [
        (
            "lookfor",
            ""
        ),

        (
            "type",
            "AllFields"
        ),

        (
            "filter[]",
            CNPQ_FILTER
        ),

        (
            "filter[]",
            f"publishDate:[{year} TO {year}]"
        ),

        (
            "page",
            page_number
        ),
    ]

    return (
        BASE_URL
        + "?"
        + urlencode(params)
    )


# ============================================================
# EXTRAÇÃO DE URLs
# ============================================================

def extract_record_urls(
    page
):
    """
    Extrai as URLs dos registros da BDTD.
    """

    urls = []

    links = page.locator(
        'a[href*="/vufind/Record/"]'
    )

    try:
        count = links.count()

    except Exception:
        return []

    for index in range(
        count
    ):

        try:
            href = (
                links
                .nth(index)
                .get_attribute(
                    "href"
                )
            )

        except Exception:
            continue

        if not href:
            continue

        href = href.strip()

        if href.startswith("/"):
            href = (
                "https://bdtd.ibict.br"
                + href
            )

        if "/vufind/Record/" not in href:
            continue

        href = (
            href
            .split("?")[0]
        )

        urls.append(
            href
        )

    return list(
        dict.fromkeys(
            urls
        )
    )


# ============================================================
# CARREGA COLETA ANTERIOR
# ============================================================

def load_existing_data():
    """
    Lê record_urls.json anterior.

    Retorna:
    - URLs existentes;
    - anos já processados.
    """

    if not RECORD_URLS_FILE.exists():
        return [], []

    try:
        with RECORD_URLS_FILE.open(
            "r",
            encoding="utf-8"
        ) as file:

            data = json.load(
                file
            )

    except Exception as error:

        print(
            "Não foi possível ler "
            "record_urls.json:",
            error
        )

        return [], []

    # Arquivo antigo em formato lista
    if isinstance(
        data,
        list
    ):
        return data, []

    if isinstance(
        data,
        dict
    ):

        urls = (
            data.get(
                "record_urls",
                []
            )
        )

        years = (
            data.get(
                "anos_processados",
                []
            )
        )

        return (
            urls,
            years
        )

    return [], []


# ============================================================
# SALVAMENTO
# ============================================================

def save_urls(
    urls,
    years_processed
):
    """
    Salva progresso da coleta.
    """

    payload = {
        "area": "Direito",

        "filtro": (
            "CNPQ::CIENCIAS SOCIAIS "
            "APLICADAS::DIREITO"
        ),

        "estrategia": (
            "particionamento por ano"
        ),

        "anos_processados": (
            years_processed
        ),

        "total": (
            len(urls)
        ),

        "record_urls": (
            urls
        ),
    }

    temp_file = (
        RECORD_URLS_FILE
        .with_suffix(
            ".tmp"
        )
    )

    with temp_file.open(
        "w",
        encoding="utf-8"
    ) as file:

        json.dump(
            payload,
            file,
            ensure_ascii=False,
            indent=2
        )

    temp_file.replace(
        RECORD_URLS_FILE
    )


# ============================================================
# RETRY
# ============================================================

def wait_before_retry(
    attempt
):
    """
    Aumenta gradualmente o intervalo
    entre tentativas.
    """

    wait_time = min(
        RETRY_WAIT_SECONDS
        * attempt,
        180
    )

    print(
        f"Aguardando "
        f"{wait_time}s..."
    )

    time.sleep(
        wait_time
    )


def open_page_with_retry(
    page,
    page_number,
    year
):
    """
    Tenta abrir a mesma página várias vezes.
    """

    url = build_search_url(
        page_number,
        year
    )

    for attempt in range(
        1,
        MAX_RETRIES_PER_PAGE + 1
    ):

        print(
            f"Tentativa "
            f"{attempt}/"
            f"{MAX_RETRIES_PER_PAGE}"
        )

        try:
            response = page.goto(
                url,
                wait_until=(
                    "domcontentloaded"
                ),
                timeout=60000
            )

            page.wait_for_timeout(
                1500
            )

            if response is not None:

                status = (
                    response.status
                )

                print(
                    "HTTP:",
                    status
                )

                if status in {
                    429,
                    500,
                    502,
                    503,
                    504,
                }:
                    raise RuntimeError(
                        f"HTTP {status}"
                    )

            body_text = (
                page.locator(
                    "body"
                )
                .inner_text()
                .lower()
            )

            markers = [
                "cannot connect",
                "connection refused",
                "service unavailable",
                "temporarily unavailable",
                "bad gateway",
                "gateway timeout",
            ]

            if any(
                marker in body_text
                for marker in markers
            ):
                raise RuntimeError(
                    "Página indisponível"
                )

            return True

        except (
            PlaywrightTimeoutError,
            Exception
        ) as error:

            print(
                "Erro:",
                error
            )

            if (
                attempt
                < MAX_RETRIES_PER_PAGE
            ):
                wait_before_retry(
                    attempt
                )

    return False


# ============================================================
# BUSCA PRINCIPAL
# ============================================================

def main():
    create_directories()

    print(
        "=" * 70
    )

    print(
        "BUSCA BDTD - DIREITO"
    )

    print(
        "=" * 70
    )

    print(
        "Meta:",
        MAX_RECORDS
    )

    print(
        "Ano inicial:",
        START_YEAR
    )

    print(
        "Ano final:",
        END_YEAR
    )

    # --------------------------------------------------------
    # NÃO reaproveitamos automaticamente URLs antigas
    # como corpus oficial.
    #
    # O arquivo anterior é apenas preservado em caso de
    # indisponibilidade completa.
    # --------------------------------------------------------

    old_urls, _ = (
        load_existing_data()
    )

    collected_urls = []

    seen = set()

    years_processed = []

    # ========================================================
    # PLAYWRIGHT
    # ========================================================

    with sync_playwright() as playwright:

        browser = (
            playwright
            .chromium
            .launch(
                headless=HEADLESS
            )
        )

        context = (
            browser
            .new_context(
                ignore_https_errors=True,
                user_agent=(
                    "Mozilla/5.0 "
                    "(Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 "
                    "(KHTML, like Gecko) "
                    "Chrome/152.0.0.0 "
                    "Safari/537.36"
                ),
            )
        )

        page = (
            context
            .new_page()
        )

        try:

            # =================================================
            # ANOS
            # =================================================

            for year in YEARS:

                if (
                    len(collected_urls)
                    >= MAX_RECORDS
                ):
                    break

                print()
                print(
                    "#" * 70
                )

                print(
                    f"ANO {year}"
                )

                print(
                    "#" * 70
                )

                page_number = 1

                year_total = 0

                year_seen = set()

                year_completed = False

                # =================================================
                # PÁGINAS
                # =================================================

                while (
                    len(collected_urls)
                    < MAX_RECORDS
                ):

                    print()
                    print(
                        "=" * 70
                    )

                    print(
                        f"Ano {year} "
                        f"- Página "
                        f"{page_number}"
                    )

                    search_url = (
                        build_search_url(
                            page_number,
                            year
                        )
                    )

                    print(
                        search_url
                    )

                    opened = (
                        open_page_with_retry(
                            page,
                            page_number,
                            year
                        )
                    )

                    # ---------------------------------------------
                    # Falha temporária
                    # ---------------------------------------------

                    if not opened:

                        print()
                        print(
                            "Não foi possível "
                            "continuar este ano."
                        )

                        print(
                            "O progresso já coletado "
                            "será preservado."
                        )

                        break

                    # ---------------------------------------------
                    # Extrai registros
                    # ---------------------------------------------

                    page_urls = (
                        extract_record_urls(
                            page
                        )
                    )

                    print(
                        "Encontrados:",
                        len(page_urls)
                    )

                    # ---------------------------------------------
                    # Fim dos resultados
                    # ---------------------------------------------

                    if not page_urls:

                        print(
                            "Nenhum resultado "
                            "nesta página."
                        )

                        year_completed = True

                        break

                    new_global = 0
                    new_year = 0

                    # ---------------------------------------------
                    # Adiciona registros
                    # ---------------------------------------------

                    for record_url in (
                        page_urls
                    ):

                        # Repetição dentro do mesmo ano
                        if (
                            record_url
                            in year_seen
                        ):
                            continue

                        year_seen.add(
                            record_url
                        )

                        new_year += 1

                        # Duplicado entre anos
                        if (
                            record_url
                            in seen
                        ):
                            continue

                        seen.add(
                            record_url
                        )

                        collected_urls.append(
                            record_url
                        )

                        year_total += 1
                        new_global += 1

                        if (
                            len(collected_urls)
                            >= MAX_RECORDS
                        ):
                            break

                    print(
                        "Novos na página:",
                        new_global
                    )

                    print(
                        f"Total {year}:",
                        year_total
                    )

                    print(
                        "Total geral:",
                        len(collected_urls)
                    )

                    # ---------------------------------------------
                    # Salva imediatamente
                    # ---------------------------------------------

                    if collected_urls:

                        save_urls(
                            collected_urls,
                            years_processed
                            + [year]
                        )

                    # ---------------------------------------------
                    # Paginação começou a repetir
                    # ---------------------------------------------

                    if new_year == 0:

                        print(
                            "A página repetiu "
                            "registros anteriores."
                        )

                        print(
                            f"Fim da paginação "
                            f"de {year}."
                        )

                        year_completed = True

                        break

                    page_number += 1

                    time.sleep(
                        random.uniform(
                            MIN_PAGE_DELAY,
                            MAX_PAGE_DELAY
                        )
                    )

                # =================================================
                # FIM DO ANO
                # =================================================

                if year_completed:

                    years_processed.append(
                        year
                    )

                print()
                print(
                    f"Fim de {year}"
                )

                print(
                    "Novos registros:",
                    year_total
                )

                print(
                    "Total geral:",
                    len(collected_urls)
                )

                if collected_urls:

                    save_urls(
                        collected_urls,
                        years_processed
                    )

        finally:

            context.close()
            browser.close()

    # ========================================================
    # FINALIZAÇÃO
    # ========================================================

    if collected_urls:

        save_urls(
            collected_urls,
            years_processed
        )

        final_urls = (
            collected_urls
        )

    elif old_urls:

        print()
        print(
            "Nenhuma nova coleta foi "
            "possível."
        )

        print(
            "Preservando arquivo "
            "anterior."
        )

        final_urls = old_urls

    else:

        final_urls = []

    print()
    print(
        "=" * 70
    )

    print(
        "BUSCA FINALIZADA"
    )

    print(
        "=" * 70
    )

    print(
        "Registros:",
        len(final_urls)
    )

    print(
        "Meta:",
        MAX_RECORDS
    )

    print(
        "Anos concluídos:",
        years_processed
    )

    print(
        "Arquivo:",
        RECORD_URLS_FILE
    )

    if (
        len(final_urls)
        >= MAX_RECORDS
    ):

        print()
        print(
            "Meta atingida."
        )

    else:

        print()
        print(
            "AVISO:"
        )

        print(
            "A meta ainda não "
            "foi atingida."
        )


if __name__ == "__main__":
    main()