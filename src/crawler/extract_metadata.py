"""
Extração dos metadados bibliográficos dos registros da BDTD.

Entrada:
    data/raw/metadata/record_urls.json

Saída:
    data/raw/metadata/records/<record_id>.json

A extração é feita somente na seção "Detalhes bibliográficos"
da página do registro, evitando confundir os metadados do trabalho
com os campos do formulário de busca da BDTD.
"""

import json
import re
from pathlib import Path

from playwright.sync_api import sync_playwright

from src.config import (
    BDTD_HEADLESS,
    METADATA_DIR,
    RECORD_URLS_FILE,
    create_directories,
)


def normalize_space(value: str | None) -> str | None:
    """
    Remove espaços e quebras de linha excedentes.
    """
    if value is None:
        return None

    value = re.sub(
        r"\s+",
        " ",
        value,
    ).strip()

    return value or None


def extract_record_id(
    record_url: str,
) -> str:
    """
    Extrai o identificador do registro a partir da URL.

    Exemplo:
        https://bdtd.ibict.br/vufind/Record/UFSC_abc123

    Retorna:
        UFSC_abc123
    """
    return (
        record_url
        .rstrip("/")
        .split("/")[-1]
    )


def get_bibliographic_lines(
    page,
) -> list[str]:
    """
    Obtém somente as linhas da seção
    'Detalhes bibliográficos'.

    Isso evita capturar campos da interface de busca,
    como:
        Ano da publicação
        Autor
        Assunto
        Resumo
    """

    body_text = (
        page.locator("body")
        .inner_text()
    )

    lines = [
        normalize_space(line)
        for line in body_text.splitlines()
    ]

    lines = [
        line
        for line in lines
        if line
    ]

    start_index = None
    end_index = None

    for index, line in enumerate(lines):
        if (
            line.lower()
            == "detalhes bibliográficos"
        ):
            start_index = index + 1
            break

    if start_index is None:
        return []

    for index in range(
        start_index,
        len(lines),
    ):
        if (
            lines[index].lower()
            == "metadados do item"
        ):
            end_index = index
            break

    if end_index is None:
        end_index = len(lines)

    return lines[
        start_index:end_index
    ]


def extract_field(
    lines: list[str],
    labels: list[str],
) -> str | None:
    """
    Extrai um campo da seção bibliográfica.

    Suporta dois formatos encontrados na BDTD:

    1.
        Ano de defesa:1983

    2.
        Autor(a) principal:
        Cleve, Clemerson Merlin
    """

    for index, line in enumerate(lines):

        for label in labels:

            # -----------------------------
            # Formato:
            # Tipo de documento:Dissertação
            # -----------------------------
            pattern = (
                rf"^{re.escape(label)}"
                rf"\s*:\s*(.+)$"
            )

            match = re.match(
                pattern,
                line,
                flags=re.IGNORECASE,
            )

            if match:
                return normalize_space(
                    match.group(1)
                )

            # -----------------------------
            # Formato:
            # Autor(a) principal:
            # Nome do autor
            # -----------------------------
            label_only_pattern = (
                rf"^{re.escape(label)}"
                rf"\s*:\s*$"
            )

            if re.match(
                label_only_pattern,
                line,
                flags=re.IGNORECASE,
            ):
                if index + 1 < len(lines):
                    return normalize_space(
                        lines[index + 1]
                    )

    return None


def extract_title(
    page,
) -> str | None:
    """
    Extrai o título principal do registro.
    """

    # Tenta títulos estruturados primeiro.
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

        text = normalize_space(
            locator.first.inner_text()
        )

        if text:
            return text

    # Fallback baseado na estrutura textual.
    body_text = (
        page.locator("body")
        .inner_text()
    )

    lines = [
        normalize_space(line)
        for line in body_text.splitlines()
    ]

    lines = [
        line
        for line in lines
        if line
    ]

    for index, line in enumerate(lines):
        if (
            line.lower()
            == "detalhes bibliográficos"
            and index > 0
        ):
            return lines[
                index - 1
            ]

    return None


def extract_metadata_from_page(
    page,
    record_url: str,
) -> dict:
    """
    Extrai os principais metadados bibliográficos
    do registro atual da BDTD.
    """

    bibliographic_lines = (
        get_bibliographic_lines(
            page
        )
    )

    record_id = extract_record_id(
        record_url
    )

    metadata = {
        "record_id": record_id,

        "source": "BDTD",

        "record_url": record_url,

        "title": extract_title(
            page
        ),

        "year": extract_field(
            bibliographic_lines,
            [
                "Ano de defesa",
                "Ano de publicação",
            ],
        ),

        "author": extract_field(
            bibliographic_lines,
            [
                "Autor(a) principal",
                "Autor principal",
                "Autor(a)",
                "Autor",
            ],
        ),

        "advisor": extract_field(
            bibliographic_lines,
            [
                "Orientador(a)",
                "Orientador",
            ],
        ),

        "document_type": extract_field(
            bibliographic_lines,
            [
                "Tipo de documento",
            ],
        ),

        "access_type": extract_field(
            bibliographic_lines,
            [
                "Tipo de acesso",
            ],
        ),

        "language": extract_field(
            bibliographic_lines,
            [
                "Idioma",
            ],
        ),

        "institution": extract_field(
            bibliographic_lines,
            [
                "Instituição de defesa",
                "Instituição",
            ],
        ),

        "graduate_program": extract_field(
            bibliographic_lines,
            [
                "Programa de Pós-Graduação",
            ],
        ),

        "department": extract_field(
            bibliographic_lines,
            [
                "Departamento",
            ],
        ),

        "country": extract_field(
            bibliographic_lines,
            [
                "País",
            ],
        ),

        "access_url": extract_field(
            bibliographic_lines,
            [
                "Link de acesso",
            ],
        ),

        "abstract": extract_field(
            bibliographic_lines,
            [
                "Resumo",
            ],
        ),
    }

    return metadata


def load_record_urls() -> list[str]:
    """
    Carrega as URLs coletadas pela etapa search_records.

    Aceita:

    Formato atual:
        {
            "record_urls": [...]
        }

    Formato antigo:
        [...]
    """

    if not RECORD_URLS_FILE.exists():
        raise FileNotFoundError(
            f"Arquivo não encontrado: "
            f"{RECORD_URLS_FILE}"
        )

    with open(
        RECORD_URLS_FILE,
        "r",
        encoding="utf-8",
    ) as file:
        data = json.load(file)

    if isinstance(
        data,
        list,
    ):
        return data

    if isinstance(
        data,
        dict,
    ):
        record_urls = data.get(
            "record_urls",
            [],
        )

        if isinstance(
            record_urls,
            list,
        ):
            return record_urls

    raise ValueError(
        "Formato inválido em "
        f"{RECORD_URLS_FILE}"
    )


def save_metadata(
    metadata: dict,
) -> Path:
    """
    Salva o metadata individual do registro.
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
    Executa a extração dos metadados de todos os
    registros coletados anteriormente.
    """

    create_directories()

    record_urls = load_record_urls()

    print(
        "Registros encontrados:",
        len(record_urls),
    )

    success = 0
    errors = 0

    with sync_playwright() as playwright:

        browser = (
            playwright.chromium.launch(
                headless=BDTD_HEADLESS,
            )
        )

        context = browser.new_context(
            viewport={
                "width": 1440,
                "height": 900,
            }
        )

        page = context.new_page()

        for index, record_url in enumerate(
            record_urls,
            start=1,
        ):
            print()
            print("=" * 60)

            print(
                f"[{index}/"
                f"{len(record_urls)}]"
            )

            print(record_url)

            try:

                page.goto(
                    record_url,
                    wait_until=(
                        "domcontentloaded"
                    ),
                    timeout=60000,
                )

                page.wait_for_timeout(
                    2000
                )

                metadata = (
                    extract_metadata_from_page(
                        page,
                        record_url,
                    )
                )

                output_file = (
                    save_metadata(
                        metadata
                    )
                )

                success += 1

                print(
                    "Título:",
                    metadata.get(
                        "title"
                    ),
                )

                print(
                    "Ano:",
                    metadata.get(
                        "year"
                    ),
                )

                print(
                    "Autor:",
                    metadata.get(
                        "author"
                    ),
                )

                print(
                    "URL:",
                    metadata.get(
                        "access_url"
                    ),
                )

                print(
                    "Salvo:",
                    output_file,
                )

            except Exception as error:

                errors += 1

                print(
                    "Erro:",
                    error,
                )

        context.close()
        browser.close()

    print()
    print("=" * 60)
    print(
        "EXTRAÇÃO FINALIZADA"
    )
    print(
        "Sucesso:",
        success,
    )
    print(
        "Erros:",
        errors,
    )


if __name__ == "__main__":
    run()