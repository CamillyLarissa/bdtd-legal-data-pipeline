import json
import os
import random
import time
from pathlib import Path
from urllib.parse import urlencode

from playwright.sync_api import sync_playwright
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError


# ============================================================
# CONFIGURAÇÃO
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
        "200"
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

# Quantas vezes tentar a mesma página
MAX_RETRIES_PER_PAGE = 8

# Espera base quando a BDTD recusar conexão
RETRY_WAIT_SECONDS = 30

# Pequena pausa entre páginas normais
MIN_PAGE_DELAY = 1.5
MAX_PAGE_DELAY = 3.0

# Quantidade padrão de resultados por página
RESULTS_PER_PAGE = 20


# ============================================================
# FILTRO OFICIAL DO CORPUS
# ============================================================

CNPQ_FILTER = (
    'dc.subject.cnpq.fl_str_mv:'
    '"CNPQ::CIENCIAS SOCIAIS APLICADAS::DIREITO"'
)


# ============================================================
# UTILIDADES
# ============================================================

def create_directories():
    METADATA_DIR.mkdir(
        parents=True,
        exist_ok=True
    )


def build_search_url(page_number):
    """
    Monta a URL da busca da BDTD usando
    o filtro CNPq da área Direito.
    """

    params = [
        ("lookfor", ""),
        ("type", "AllFields"),
        (
            "filter[]",
            CNPQ_FILTER
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


def extract_record_urls(page):
    """
    Extrai os links dos registros individuais
    presentes na página de resultados.
    """

    urls = []

    links = page.locator(
        'a[href*="/vufind/Record/"]'
    )

    count = links.count()

    for i in range(count):
        try:
            href = links.nth(i).get_attribute(
                "href"
            )

            if not href:
                continue

            if href.startswith("/"):
                href = (
                    "https://bdtd.ibict.br"
                    + href
                )

            if "/vufind/Record/" not in href:
                continue

            # Remove parâmetros extras da URL
            href = href.split("?")[0]

            urls.append(href)

        except Exception:
            continue

    # Remove duplicatas preservando ordem
    unique_urls = list(
        dict.fromkeys(urls)
    )

    return unique_urls


def load_existing_urls():
    """
    Carrega coleta anterior, caso exista.

    Isso impede que uma falha momentânea
    sobrescreva uma coleta válida.
    """

    if not RECORD_URLS_FILE.exists():
        return []

    try:
        with RECORD_URLS_FILE.open(
            "r",
            encoding="utf-8"
        ) as f:
            data = json.load(f)

        if isinstance(data, list):
            return data

        if isinstance(data, dict):
            return data.get(
                "record_urls",
                []
            )

    except Exception as exc:
        print(
            f"Aviso: não foi possível "
            f"carregar coleta anterior: {exc}"
        )

    return []


def save_urls(urls):
    """
    Salva progresso incrementalmente.
    """

    payload = {
        "area": "Direito",
        "filtro": (
            "CNPQ::CIENCIAS SOCIAIS "
            "APLICADAS::DIREITO"
        ),
        "total": len(urls),
        "record_urls": urls,
    }

    temp_file = (
        RECORD_URLS_FILE
        .with_suffix(".tmp")
    )

    with temp_file.open(
        "w",
        encoding="utf-8"
    ) as f:
        json.dump(
            payload,
            f,
            ensure_ascii=False,
            indent=2
        )

    # Escrita atômica:
    # só substitui o arquivo final
    # depois que o JSON foi escrito.
    temp_file.replace(
        RECORD_URLS_FILE
    )


def wait_before_retry(attempt):
    """
    Espera progressivamente mais entre
    as tentativas da mesma página.
    """

    wait_time = (
        RETRY_WAIT_SECONDS
        * attempt
    )

    # Limita a espera máxima
    wait_time = min(
        wait_time,
        180
    )

    print(
        f"Aguardando {wait_time}s "
        "antes de tentar novamente..."
    )

    time.sleep(wait_time)


# ============================================================
# ABERTURA DA PÁGINA COM RETRY
# ============================================================

def open_page_with_retry(
    page,
    page_number
):
    """
    Tenta abrir a mesma página várias vezes
    antes de desistir.
    """

    url = build_search_url(
        page_number
    )

    for attempt in range(
        1,
        MAX_RETRIES_PER_PAGE + 1
    ):

        print()
        print(
            f"Tentativa {attempt}/"
            f"{MAX_RETRIES_PER_PAGE}"
        )

        try:
            response = page.goto(
                url,
                wait_until="domcontentloaded",
                timeout=60000
            )

            # Pequena espera para a página
            # terminar de renderizar.
            page.wait_for_timeout(
                1500
            )

            title = page.title()

            print(
                f"Título: {title}"
            )

            # Se houve resposta HTTP,
            # mostra o status.
            if response is not None:
                print(
                    "HTTP:",
                    response.status
                )

                # Erros temporários do servidor
                if response.status in {
                    429,
                    500,
                    502,
                    503,
                    504,
                }:
                    raise RuntimeError(
                        f"HTTP {response.status}"
                    )

            # Verifica páginas de erro
            body_text = (
                page.locator("body")
                .inner_text()
                .lower()
            )

            error_markers = [
                "cannot connect",
                "connection refused",
                "service unavailable",
                "temporarily unavailable",
                "bad gateway",
                "gateway timeout",
            ]

            if any(
                marker in body_text
                for marker in error_markers
            ):
                raise RuntimeError(
                    "Página de erro/indisponibilidade"
                )

            return True, url

        except (
            PlaywrightTimeoutError,
            Exception
        ) as exc:

            print(
                f"Erro ao abrir página "
                f"{page_number}: {exc}"
            )

            if (
                attempt
                < MAX_RETRIES_PER_PAGE
            ):
                wait_before_retry(
                    attempt
                )

    return False, url


# ============================================================
# BUSCA
# ============================================================

def main():
    create_directories()

    print(
        "Consulta: Direito"
    )
    print(
        f"Limite: {MAX_RECORDS}"
    )

    existing_urls = (
        load_existing_urls()
    )

    # Começamos uma nova coleta,
    # mas preservamos a antiga em memória.
    collected_urls = []

    seen = set()

    page_number = 1

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=HEADLESS
        )

        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 "
                "(Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 "
                "(KHTML, like Gecko) "
                "Chrome/152.0.0.0 "
                "Safari/537.36"
            )
        )

        page = context.new_page()

        try:
            while (
                len(collected_urls)
                < MAX_RECORDS
            ):
                print()
                print(
                    "=" * 70
                )
                print(
                    f"Página {page_number}"
                )

                search_url = (
                    build_search_url(
                        page_number
                    )
                )

                print(
                    search_url
                )

                success, _ = (
                    open_page_with_retry(
                        page,
                        page_number
                    )
                )

                # ====================================================
                # BDTD ficou indisponível
                # ====================================================

                if not success:
                    print()
                    print(
                        "BDTD indisponível após "
                        "todas as tentativas."
                    )

                    print(
                        "A coleta parcial será "
                        "preservada."
                    )

                    break

                # ====================================================
                # EXTRAI LINKS
                # ====================================================

                page_urls = (
                    extract_record_urls(
                        page
                    )
                )

                found_count = len(
                    page_urls
                )

                print(
                    "Encontrados na página:",
                    found_count
                )

                # ====================================================
                # SEM RESULTADOS
                # ====================================================

                if found_count == 0:
                    print(
                        "Nenhum registro encontrado."
                    )

                    print(
                        "Fim dos resultados."
                    )

                    break

                # ====================================================
                # ADICIONA NOVOS
                # ====================================================

                new_count = 0

                for url in page_urls:
                    if url in seen:
                        continue

                    seen.add(url)

                    collected_urls.append(
                        url
                    )

                    new_count += 1

                    if (
                        len(collected_urls)
                        >= MAX_RECORDS
                    ):
                        break

                print(
                    "Novos:",
                    new_count
                )

                print(
                    "Total coletado:",
                    len(collected_urls)
                )

                # ====================================================
                # SALVAMENTO INCREMENTAL
                # ====================================================

                if collected_urls:
                    save_urls(
                        collected_urls
                    )

                # ====================================================
                # PROTEÇÃO CONTRA LOOP
                # ====================================================

                if new_count == 0:
                    print(
                        "Página sem novos registros."
                    )

                    print(
                        "Interrompendo para evitar loop."
                    )

                    break

                page_number += 1

                time.sleep(
                    random.uniform(
                        MIN_PAGE_DELAY,
                        MAX_PAGE_DELAY
                    )
                )

        finally:
            context.close()
            browser.close()

    # ============================================================
    # FINALIZAÇÃO SEGURA
    # ============================================================

    if collected_urls:
        save_urls(
            collected_urls
        )

        final_urls = (
            collected_urls
        )

    else:
        # Se nenhuma página conseguiu ser
        # coletada, preserva coleta anterior.
        if existing_urls:
            print()
            print(
                "Nenhum registro novo foi "
                "coletado."
            )

            print(
                "Mantendo record_urls.json "
                "anterior."
            )

            final_urls = (
                existing_urls
            )

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
        "Arquivo:",
        RECORD_URLS_FILE
    )

    if (
        len(final_urls)
        < MAX_RECORDS
    ):
        print()
        print(
            "AVISO: coleta incompleta."
        )

        print(
            f"Obtidos: {len(final_urls)}"
        )

        print(
            f"Meta: {MAX_RECORDS}"
        )


# ============================================================
# EXECUÇÃO
# ============================================================

if __name__ == "__main__":
    main()