"""
Extração dos metadados bibliográficos dos registros da BDTD.

Entrada:
    data/raw/metadata/record_urls.json

Saída:
    data/raw/metadata/records/<record_id>.json
    data/raw/metadata/failed_metadata.json

A extração possui tentativas e validação para evitar salvar
páginas incompletas como se fossem metadados válidos.
"""

import json
import re
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

from src.config import (
    BDTD_HEADLESS,
    METADATA_DIR,
    RECORD_URLS_FILE,
    create_directories,
)


MAX_RETRIES = 3
WAIT_AFTER_LOAD_MS = 2500
WAIT_BETWEEN_RECORDS = 1.5
WAIT_BETWEEN_RETRIES = 5


# ============================================================
# UTILITÁRIOS
# ============================================================

def normalize_space(
    value: str | None,
) -> str | None:
    """Remove espaços e quebras de linha excedentes."""

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
    """Extrai o ID do registro da URL."""

    return (
        record_url
        .rstrip("/")
        .split("/")[-1]
    )


def get_page_lines(
    page,
) -> list[str]:
    """Obtém todas as linhas textuais úteis da página."""

    body_text = (
        page.locator("body")
        .inner_text()
    )

    lines = [
        normalize_space(line)
        for line in body_text.splitlines()
    ]

    return [
        line
        for line in lines
        if line
    ]


# ============================================================
# VALIDAÇÃO DA PÁGINA
# ============================================================

def page_has_metadata(
    page,
) -> bool:
    """
    Verifica se a página realmente carregou os metadados
    bibliográficos do registro.
    """

    try:
        body_text = (
            page.locator("body")
            .inner_text()
            .lower()
        )

    except Exception:
        return False

    indicators = [
        "ano de defesa",
        "ano de publicação",
        "autor(a) principal",
        "tipo de documento",
    ]

    return any(
        indicator in body_text
        for indicator in indicators
    )


def wait_for_metadata(
    page,
) -> bool:
    """
    Aguarda os metadados aparecerem na página.

    Não depende somente de um tempo fixo.
    """

    try:

        page.wait_for_function(
            """
            () => {
                const text =
                    document.body.innerText.toLowerCase();

                return (
                    text.includes('ano de defesa') ||
                    text.includes('ano de publicação') ||
                    text.includes('autor(a) principal')
                );
            }
            """,
            timeout=15000,
        )

        return True

    except Exception:

        return page_has_metadata(
            page
        )


# ============================================================
# SEÇÃO BIBLIOGRÁFICA
# ============================================================

def get_bibliographic_lines(
    page,
) -> list[str]:
    """
    Obtém as linhas da área bibliográfica.

    Funciona tanto para páginas com o título
    'Detalhes bibliográficos' quanto para páginas
    em que os campos aparecem diretamente.
    """

    lines = get_page_lines(
        page
    )

    # --------------------------------------------------------
    # Estrutura com "Detalhes bibliográficos"
    # --------------------------------------------------------

    for index, line in enumerate(
        lines
    ):

        if (
            line.lower().strip()
            == "detalhes bibliográficos"
        ):

            return lines[
                index + 1:
            ]

    # --------------------------------------------------------
    # Estrutura atual da BDTD
    # --------------------------------------------------------

    labels = [
        "ano de defesa",
        "ano de publicação",
        "autor(a) principal",
        "autor principal",
    ]

    for index, line in enumerate(
        lines
    ):

        current = (
            line.lower()
            .strip()
        )

        if any(
            current.startswith(label)
            for label in labels
        ):

            return lines[
                max(0, index - 3):
            ]

    return []


# ============================================================
# EXTRAÇÃO DE CAMPOS
# ============================================================

def extract_field(
    lines: list[str],
    labels: list[str],
) -> str | None:
    """
    Extrai valores em formatos como:

        Ano de defesa: 2024

    ou:

        Ano de defesa:
        2024
    """

    for index, line in enumerate(
        lines
    ):

        for label in labels:

            # Campo e valor na mesma linha
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

            # Label em uma linha e valor na próxima
            label_only_pattern = (
                rf"^{re.escape(label)}"
                rf"\s*:\s*$"
            )

            if re.match(
                label_only_pattern,
                line,
                flags=re.IGNORECASE,
            ):

                if (
                    index + 1
                    < len(lines)
                ):

                    return normalize_space(
                        lines[index + 1]
                    )

    return None


# ============================================================
# TÍTULO
# ============================================================

def extract_title(
    page,
) -> str | None:
    """Extrai o título principal do trabalho."""

    selectors = [
        "h1",
        ".record-title",
        ".title",
        "h2",
    ]

    for selector in selectors:

        locator = page.locator(
            selector
        )

        if locator.count() == 0:
            continue

        try:

            text = normalize_space(
                locator.first.inner_text()
            )

        except Exception:
            continue

        if (
            text
            and len(text) > 5
            and text.lower()
            not in {
                "metadados do item",
                "detalhes bibliográficos",
            }
        ):
            return text

    # --------------------------------------------------------
    # Fallback textual
    # --------------------------------------------------------

    lines = get_page_lines(
        page
    )

    for index, line in enumerate(
        lines
    ):

        current = (
            line.lower()
            .strip()
        )

        if (
            current.startswith(
                "ano de defesa"
            )
            or current.startswith(
                "ano de publicação"
            )
        ):

            if index > 0:

                return normalize_space(
                    lines[index - 1]
                )

    return None


# ============================================================
# LIMPEZA
# ============================================================

def clean_value(
    value: str | None,
) -> str | None:
    """Normaliza valores considerados ausentes."""

    value = normalize_space(
        value
    )

    if value is None:
        return None

    normalized = (
        value.lower()
        .strip()
    )

    missing = {
        "não informado",
        "não informado pela instituição",
        "nao informado",
        "nao informado pela instituicao",
        "não disponível",
        "nao disponivel",
        "-",
    }

    if normalized in missing:
        return None

    return value


# ============================================================
# EXTRAÇÃO
# ============================================================

def extract_metadata_from_page(
    page,
    record_url: str,
) -> dict:
    """Extrai os principais metadados do registro."""

    lines = get_bibliographic_lines(
        page
    )

    metadata = {
        "record_id": extract_record_id(
            record_url
        ),

        "source": "BDTD",

        "record_url": record_url,

        "title": extract_title(
            page
        ),

        "year": extract_field(
            lines,
            [
                "Ano de defesa",
                "Ano de publicação",
                "Ano",
            ],
        ),

        "author": extract_field(
            lines,
            [
                "Autor(a) principal",
                "Autor principal",
                "Autor(a)",
                "Autor",
            ],
        ),

        "advisor": extract_field(
            lines,
            [
                "Orientador(a)",
                "Orientador",
            ],
        ),

        "document_type": extract_field(
            lines,
            [
                "Tipo de documento",
            ],
        ),

        "access_type": extract_field(
            lines,
            [
                "Tipo de acesso",
            ],
        ),

        "language": extract_field(
            lines,
            [
                "Idioma",
            ],
        ),

        "institution": extract_field(
            lines,
            [
                "Instituição de defesa",
                "Instituição",
            ],
        ),

        "graduate_program": extract_field(
            lines,
            [
                "Programa de Pós-Graduação",
                "Programa de Pós Graduação",
            ],
        ),

        "department": extract_field(
            lines,
            [
                "Departamento",
            ],
        ),

        "country": extract_field(
            lines,
            [
                "País",
                "Pais",
            ],
        ),

        "access_url": extract_field(
            lines,
            [
                "Link de acesso",
                "URL de acesso",
            ],
        ),

        "abstract": extract_field(
            lines,
            [
                "Resumo",
            ],
        ),
    }

    for key in [
        "title",
        "year",
        "author",
        "advisor",
        "document_type",
        "access_type",
        "language",
        "institution",
        "graduate_program",
        "department",
        "country",
        "access_url",
        "abstract",
    ]:

        metadata[key] = clean_value(
            metadata.get(key)
        )

    return metadata


# ============================================================
# VALIDAÇÃO DOS METADADOS
# ============================================================

def metadata_is_valid(
    metadata: dict,
) -> bool:
    """
    Considera inválida uma extração em que os principais
    campos estão todos ausentes.
    """

    important_fields = [
        metadata.get("title"),
        metadata.get("year"),
        metadata.get("author"),
    ]

    return any(
        important_fields
    )


# ============================================================
# ENTRADA
# ============================================================

def load_record_urls() -> list[str]:
    """Carrega as URLs produzidas pelo search_records."""

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

        data = json.load(
            file
        )

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
        f"Formato inválido em "
        f"{RECORD_URLS_FILE}"
    )


# ============================================================
# SAÍDA
# ============================================================

def save_metadata(
    metadata: dict,
) -> Path:
    """Salva metadata individual."""

    output_file = (
        METADATA_DIR
        / f"{metadata['record_id']}.json"
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


def save_failed(
    failures: list[dict],
) -> None:
    """Salva lista de registros que não puderam ser extraídos."""

    output = (
        METADATA_DIR.parent
        / "failed_metadata.json"
    )

    with open(
        output,
        "w",
        encoding="utf-8",
    ) as file:

        json.dump(
            failures,
            file,
            ensure_ascii=False,
            indent=2,
        )


# ============================================================
# EXECUÇÃO
# ============================================================

def run() -> None:

    create_directories()

    record_urls = load_record_urls()

    print(
        "Registros encontrados:",
        len(record_urls),
    )

    success = 0
    failed_count = 0

    failures = []

    with sync_playwright() as playwright:

        browser = (
            playwright.chromium.launch(
                headless=BDTD_HEADLESS,
            )
        )

        context = (
            browser.new_context(
                viewport={
                    "width": 1440,
                    "height": 900,
                }
            )
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

            print(
                record_url
            )

            metadata = None

            # =================================================
            # TENTATIVAS
            # =================================================

            for attempt in range(
                1,
                MAX_RETRIES + 1,
            ):

                print(
                    f"Tentativa "
                    f"{attempt}/"
                    f"{MAX_RETRIES}"
                )

                try:

                    page.goto(
                        record_url,
                        wait_until="domcontentloaded",
                        timeout=60000,
                    )

                    page.wait_for_timeout(
                        WAIT_AFTER_LOAD_MS
                    )

                    loaded = wait_for_metadata(
                        page
                    )

                    if not loaded:

                        print(
                            "Metadados ainda não apareceram."
                        )

                        if attempt < MAX_RETRIES:
                            time.sleep(
                                WAIT_BETWEEN_RETRIES
                            )

                        continue

                    candidate = (
                        extract_metadata_from_page(
                            page,
                            record_url,
                        )
                    )

                    if metadata_is_valid(
                        candidate
                    ):

                        metadata = candidate
                        break

                    print(
                        "Página carregada, mas "
                        "metadados principais vazios."
                    )

                except Exception as error:

                    print(
                        "Erro:",
                        error,
                    )

                if attempt < MAX_RETRIES:

                    print(
                        "Aguardando antes "
                        "de tentar novamente..."
                    )

                    time.sleep(
                        WAIT_BETWEEN_RETRIES
                    )

            # =================================================
            # SUCESSO
            # =================================================

            if metadata:

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
                    "Instituição:",
                    metadata.get(
                        "institution"
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

            # =================================================
            # FALHA
            # =================================================

            else:

                failed_count += 1

                record_id = (
                    extract_record_id(
                        record_url
                    )
                )

                failures.append(
                    {
                        "record_id": record_id,
                        "record_url": record_url,
                        "reason": (
                            "metadata_not_loaded"
                        ),
                    }
                )

                print(
                    "FALHA: metadados "
                    "não foram obtidos."
                )

            save_failed(
                failures
            )

            time.sleep(
                WAIT_BETWEEN_RECORDS
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
        "Falhas:",
        failed_count,
    )

    print(
        "Arquivo de falhas:",
        METADATA_DIR.parent
        / "failed_metadata.json",
    )


if __name__ == "__main__":
    run()