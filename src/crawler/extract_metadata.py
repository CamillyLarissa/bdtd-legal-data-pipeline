"""
Extrai metadados dos registros encontrados na BDTD.

Entrada:
    data/raw/metadata/record_urls.json

Saída:
    data/raw/metadata/records/<record_id>.json

Esta é a camada Raw. Por isso, os valores são preservados
o máximo possível conforme aparecem na BDTD.
"""

import json
import re
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright

from src.config import (
    BDTD_HEADLESS,
    METADATA_DIR,
    PAGE_TIMEOUT,
    RECORD_URLS_FILE,
    create_directories,
)


def load_record_urls() -> list[str]:
    """
    Carrega as URLs dos registros.

    Aceita dois formatos:

    1. lista simples:
       ["url1", "url2"]

    2. estrutura atual:
       {"record_urls": [...]}
    """
    if not RECORD_URLS_FILE.exists():
        raise FileNotFoundError(
            "Arquivo de URLs não encontrado: "
            f"{RECORD_URLS_FILE}"
        )

    with open(
        RECORD_URLS_FILE,
        "r",
        encoding="utf-8",
    ) as file:
        data = json.load(file)

    if isinstance(data, list):
        return data

    if isinstance(data, dict):
        urls = data.get(
            "record_urls",
            [],
        )

        if isinstance(urls, list):
            return urls

    raise ValueError(
        "Formato inválido de record_urls.json"
    )


def extract_record_id(
    record_url: str,
) -> str:
    """
    Obtém o identificador do registro a partir da URL.

    Exemplo:
        .../Record/UFSC_abc123

        -> UFSC_abc123
    """
    match = re.search(
        r"/Record/([^/?#]+)",
        record_url,
    )

    if match:
        return match.group(1)

    safe_id = re.sub(
        r"[^a-zA-Z0-9_-]+",
        "_",
        record_url,
    )

    return safe_id[-100:]


def clean_value(
    value: str | None,
) -> str | None:
    """
    Remove apenas espaços excessivos externos.
    """
    if value is None:
        return None

    value = value.strip()

    if not value:
        return None

    return value


def extract_label(
    body_text: str,
    labels: list[str],
) -> str | None:
    """
    Procura valores associados a rótulos visíveis na página.

    A função aceita diferentes nomes porque registros da BDTD
    podem apresentar pequenas variações de layout.
    """
    for label in labels:
        pattern = (
            rf"(?:^|\n)\s*"
            rf"{re.escape(label)}"
            rf"\s*:?\s*\n?"
            rf"([^\n]+)"
        )

        match = re.search(
            pattern,
            body_text,
            flags=re.IGNORECASE,
        )

        if match:
            return clean_value(
                match.group(1)
            )

    return None


def extract_title(
    page,
) -> str | None:
    """
    Tenta obter o título do registro.
    """
    selectors = [
        "h1",
        ".record-title",
        ".title",
    ]

    for selector in selectors:
        locator = page.locator(
            selector
        )

        if locator.count() == 0:
            continue

        try:
            text = locator.first.inner_text()
        except Exception:
            continue

        text = clean_value(text)

        if text:
            return text

    return None


def is_external_url(
    url: str,
) -> bool:
    """
    Verifica se um link pode representar uma URL externa
    de acesso ao documento.
    """
    if not url:
        return False

    if not url.startswith(
        ("http://", "https://")
    ):
        return False

    parsed = urlparse(url)

    hostname = (
        parsed.hostname
        or ""
    ).lower()

    if (
        hostname.endswith(
            "bdtd.ibict.br"
        )
    ):
        return False

    ignored_hosts = {
        "creativecommons.org",
        "facebook.com",
        "twitter.com",
        "x.com",
        "instagram.com",
        "youtube.com",
    }

    if any(
        hostname.endswith(host)
        for host in ignored_hosts
    ):
        return False

    return True


def extract_external_urls(
    page,
) -> list[str]:
    """
    Coleta URLs externas presentes no registro.

    O downloader posteriormente decide quais delas podem levar
    ao documento.
    """
    urls: list[str] = []
    seen: set[str] = set()

    anchors = page.locator(
        "a[href]"
    )

    for index in range(
        anchors.count()
    ):
        href = anchors.nth(
            index
        ).get_attribute("href")

        if not href:
            continue

        if not is_external_url(
            href
        ):
            continue

        if href in seen:
            continue

        seen.add(href)
        urls.append(href)

    return urls


def extract_metadata(
    page,
    record_url: str,
) -> dict:
    """
    Extrai os principais campos bibliográficos da página.
    """
    page.goto(
        record_url,
        wait_until="domcontentloaded",
        timeout=PAGE_TIMEOUT,
    )

    page.wait_for_timeout(1000)

    body_text = page.locator(
        "body"
    ).inner_text()

    record_id = extract_record_id(
        record_url
    )

    access_urls = (
        extract_external_urls(
            page
        )
    )

    return {
        "record_id": record_id,
        "source": "BDTD",
        "record_url": record_url,
        "title": extract_title(page),
        "year": extract_label(
            body_text,
            [
                "Ano",
                "Data",
            ],
        ),
        "author": extract_label(
            body_text,
            [
                "Autor",
                "Autor(a)",
            ],
        ),
        "advisor": extract_label(
            body_text,
            [
                "Orientador",
                "Orientador(a)",
            ],
        ),
        "document_type": extract_label(
            body_text,
            [
                "Tipo",
                "Tipo de documento",
            ],
        ),
        "access_type": extract_label(
            body_text,
            [
                "Tipo de Acesso",
                "Acesso",
            ],
        ),
        "language": extract_label(
            body_text,
            [
                "Idioma",
                "Língua",
            ],
        ),
        "institution": extract_label(
            body_text,
            [
                "Instituição",
                "Instituição de defesa",
            ],
        ),
        "graduate_program": extract_label(
            body_text,
            [
                "Programa",
                "Programa de Pós-Graduação",
            ],
        ),
        "department": extract_label(
            body_text,
            [
                "Departamento",
            ],
        ),
        "country": extract_label(
            body_text,
            [
                "País",
            ],
        ),
        "access_url": (
            "\n".join(
                access_urls
            )
            if access_urls
            else None
        ),
        "abstract": extract_label(
            body_text,
            [
                "Resumo",
            ],
        ),
    }


def save_metadata(
    metadata: dict,
) -> Path:
    """
    Salva um registro de metadados em JSON.
    """
    record_id = metadata[
        "record_id"
    ]

    output_file = (
        METADATA_DIR
        / f"{record_id}.json"
    )

    with open(
        output_file,
        "w",
        encoding="utf-8",
    ) as file:
        json.dump(
            metadata,
            file,
            ensure_ascii=False,
            indent=2,
        )

    return output_file


def run() -> None:
    """
    Processa todos os registros coletados.
    """
    create_directories()

    record_urls = (
        load_record_urls()
    )

    print(
        f"Registros encontrados: "
        f"{len(record_urls)}"
    )

    success = 0
    errors = 0

    with sync_playwright() as playwright:
        browser = (
            playwright.chromium.launch(
                headless=BDTD_HEADLESS,
            )
        )

        page = browser.new_page()

        page.set_default_timeout(
            PAGE_TIMEOUT
        )

        for index, record_url in enumerate(
            record_urls,
            start=1,
        ):
            record_id = (
                extract_record_id(
                    record_url
                )
            )

            output_file = (
                METADATA_DIR
                / f"{record_id}.json"
            )

            print(
                "\n"
                + "=" * 60
            )

            print(
                f"[{index}/"
                f"{len(record_urls)}] "
                f"{record_id}"
            )

            # Preserva metadados já existentes.
            if output_file.exists():
                print(
                    "Metadado já existe. "
                    "Pulando."
                )
                success += 1
                continue

            try:
                metadata = (
                    extract_metadata(
                        page,
                        record_url,
                    )
                )

                saved_file = (
                    save_metadata(
                        metadata
                    )
                )

                success += 1

                print(
                    f"Salvo em: "
                    f"{saved_file}"
                )

            except Exception as error:
                errors += 1

                print(
                    "Erro:",
                    error,
                )

        browser.close()

    print(
        "\n"
        + "=" * 60
    )

    print(
        "EXTRAÇÃO FINALIZADA"
    )

    print(
        f"Sucesso: {success}"
    )

    print(
        f"Erros: {errors}"
    )


if __name__ == "__main__":
    run()