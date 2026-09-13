"""
Extração dos metadados bibliográficos dos registros da BDTD.

Entrada:
    data/raw/metadata/record_urls.json

Saída:
    data/raw/metadata/records/<record_id>.json

A extração considera diferentes estruturas encontradas
nas páginas de registros da BDTD.
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


# ============================================================
# UTILITÁRIOS
# ============================================================

def normalize_space(
    value: str | None,
) -> str | None:
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


# ============================================================
# TEXTO DA PÁGINA
# ============================================================

def get_page_lines(
    page,
) -> list[str]:
    """
    Retorna todas as linhas textuais úteis da página.
    """

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
# SEÇÃO BIBLIOGRÁFICA
# ============================================================

def get_bibliographic_lines(
    page,
) -> list[str]:
    """
    Obtém as linhas referentes aos metadados bibliográficos.

    A BDTD apresenta mais de uma estrutura de página.

    Estrutura 1:
        Detalhes bibliográficos
        Ano de defesa:
        2024
        Autor(a) principal:
        ...

    Estrutura 2:
        Título
        Ano de defesa:
        2024
        Autor(a) principal:
        ...

    A função suporta os dois casos.
    """

    lines = get_page_lines(page)

    # ========================================================
    # ESTRATÉGIA 1
    # Página contendo "Detalhes bibliográficos"
    # ========================================================

    for index, line in enumerate(lines):

        if (
            line.lower().strip()
            == "detalhes bibliográficos"
        ):

            start_index = index + 1
            end_index = len(lines)

            # Alguns layouts possuem outra seção depois.
            for end in range(
                start_index,
                len(lines),
            ):

                current = (
                    lines[end]
                    .lower()
                    .strip()
                )

                if current in {
                    "metadados do item",
                    "itens relacionados",
                    "registros relacionados",
                }:
                    end_index = end
                    break

            return lines[
                start_index:end_index
            ]

    # ========================================================
    # ESTRATÉGIA 2
    # Página sem "Detalhes bibliográficos".
    #
    # Procuramos o primeiro campo bibliográfico conhecido.
    # ========================================================

    first_labels = [
        "ano de defesa",
        "ano de publicação",
        "autor(a) principal",
        "autor principal",
    ]

    for index, line in enumerate(lines):

        normalized_line = (
            line.lower()
            .strip()
        )

        for label in first_labels:

            if normalized_line.startswith(
                label
            ):

                # Mantém algumas linhas anteriores porque
                # normalmente incluem o título.
                start_index = max(
                    0,
                    index - 3,
                )

                return lines[
                    start_index:
                ]

    # ========================================================
    # FALLBACK
    # ========================================================

    return []


# ============================================================
# EXTRAÇÃO GENÉRICA DE CAMPO
# ============================================================

def extract_field(
    lines: list[str],
    labels: list[str],
) -> str | None:
    """
    Extrai um campo usando diferentes formatos encontrados
    na BDTD.

    Exemplos:

        Ano de defesa: 2024

        Ano de defesa:
        2024

        Autor(a) principal:
        Souza, Lucas Nicholas Santos de
    """

    for index, line in enumerate(lines):

        for label in labels:

            # =================================================
            # FORMATO 1
            #
            # Ano de defesa: 2024
            # =================================================

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

                value = normalize_space(
                    match.group(1)
                )

                if value:
                    return value

            # =================================================
            # FORMATO 2
            #
            # Ano de defesa:
            # 2024
            # =================================================

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

                    value = normalize_space(
                        lines[index + 1]
                    )

                    if value:
                        return value

    return None


# ============================================================
# TÍTULO
# ============================================================

def extract_title(
    page,
) -> str | None:
    """
    Extrai o título principal do registro.
    """

    # ========================================================
    # PRIMEIRA ESTRATÉGIA
    # Seletores HTML conhecidos
    # ========================================================

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

    # ========================================================
    # SEGUNDA ESTRATÉGIA
    #
    # O título normalmente aparece imediatamente antes de:
    # "Ano de defesa"
    # ========================================================

    lines = get_page_lines(page)

    labels = [
        "ano de defesa",
        "ano de publicação",
    ]

    for index, line in enumerate(lines):

        current = (
            line.lower()
            .strip()
        )

        for label in labels:

            if current.startswith(label):

                if index > 0:

                    candidate = normalize_space(
                        lines[index - 1]
                    )

                    if candidate:
                        return candidate

    # ========================================================
    # TERCEIRA ESTRATÉGIA
    # Layout antigo com "Detalhes bibliográficos"
    # ========================================================

    for index, line in enumerate(lines):

        if (
            line.lower().strip()
            == "detalhes bibliográficos"
            and index > 0
        ):

            return normalize_space(
                lines[index - 1]
            )

    return None


# ============================================================
# LIMPEZA DE VALORES "NÃO INFORMADO"
# ============================================================

def clean_metadata_value(
    value: str | None,
) -> str | None:
    """
    Converte valores equivalentes a informação ausente
    para None.

    Exemplo:
        "Não Informado pela instituição"
        -> None
    """

    if value is None:
        return None

    value = normalize_space(
        value
    )

    if value is None:
        return None

    normalized = (
        value.lower()
        .strip()
    )

    missing_values = {
        "não informado",
        "não informado pela instituição",
        "nao informado",
        "nao informado pela instituicao",
        "não disponível",
        "nao disponivel",
        "-",
    }

    if normalized in missing_values:
        return None

    return value


# ============================================================
# EXTRAÇÃO DOS METADADOS
# ============================================================

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

        # ----------------------------------------------------
        # Título
        # ----------------------------------------------------

        "title": extract_title(
            page
        ),

        # ----------------------------------------------------
        # Ano
        # ----------------------------------------------------

        "year": extract_field(
            bibliographic_lines,
            [
                "Ano de defesa",
                "Ano de publicação",
                "Ano",
            ],
        ),

        # ----------------------------------------------------
        # Autor
        # ----------------------------------------------------

        "author": extract_field(
            bibliographic_lines,
            [
                "Autor(a) principal",
                "Autor principal",
                "Autor(a)",
                "Autor",
            ],
        ),

        # ----------------------------------------------------
        # Orientador
        # ----------------------------------------------------

        "advisor": extract_field(
            bibliographic_lines,
            [
                "Orientador(a)",
                "Orientador",
            ],
        ),

        # ----------------------------------------------------
        # Tipo de documento
        # ----------------------------------------------------

        "document_type": extract_field(
            bibliographic_lines,
            [
                "Tipo de documento",
            ],
        ),

        # ----------------------------------------------------
        # Tipo de acesso
        # ----------------------------------------------------

        "access_type": extract_field(
            bibliographic_lines,
            [
                "Tipo de acesso",
            ],
        ),

        # ----------------------------------------------------
        # Idioma
        # ----------------------------------------------------

        "language": extract_field(
            bibliographic_lines,
            [
                "Idioma",
            ],
        ),

        # ----------------------------------------------------
        # Instituição
        # ----------------------------------------------------

        "institution": extract_field(
            bibliographic_lines,
            [
                "Instituição de defesa",
                "Instituição",
            ],
        ),

        # ----------------------------------------------------
        # Programa
        # ----------------------------------------------------

        "graduate_program": extract_field(
            bibliographic_lines,
            [
                "Programa de Pós-Graduação",
                "Programa de Pós Graduação",
            ],
        ),

        # ----------------------------------------------------
        # Departamento
        # ----------------------------------------------------

        "department": extract_field(
            bibliographic_lines,
            [
                "Departamento",
            ],
        ),

        # ----------------------------------------------------
        # País
        # ----------------------------------------------------

        "country": extract_field(
            bibliographic_lines,
            [
                "País",
                "Pais",
            ],
        ),

        # ----------------------------------------------------
        # Link externo
        # ----------------------------------------------------

        "access_url": extract_field(
            bibliographic_lines,
            [
                "Link de acesso",
                "URL de acesso",
                "Acesso",
            ],
        ),

        # ----------------------------------------------------
        # Resumo
        # ----------------------------------------------------

        "abstract": extract_field(
            bibliographic_lines,
            [
                "Resumo",
            ],
        ),
    }

    # ========================================================
    # LIMPEZA
    # ========================================================

    fields_to_clean = [
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
    ]

    for field in fields_to_clean:

        metadata[field] = (
            clean_metadata_value(
                metadata.get(field)
            )
        )

    return metadata


# ============================================================
# CARREGAMENTO DAS URLs
# ============================================================

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

    # ========================================================
    # FORMATO ANTIGO
    # ========================================================

    if isinstance(
        data,
        list,
    ):
        return data

    # ========================================================
    # FORMATO ATUAL
    # ========================================================

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


# ============================================================
# SALVAMENTO
# ============================================================

def save_metadata(
    metadata: dict,
) -> Path:
    """
    Salva os metadados individuais do registro.
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


# ============================================================
# EXECUÇÃO
# ============================================================

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

    missing_title = 0
    missing_year = 0
    missing_author = 0

    # ========================================================
    # PLAYWRIGHT
    # ========================================================

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

        # ====================================================
        # REGISTROS
        # ====================================================

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

            try:

                # --------------------------------------------
                # Abre registro
                # --------------------------------------------

                page.goto(
                    record_url,
                    wait_until="domcontentloaded",
                    timeout=60000,
                )

                # Pequena espera para garantir que os
                # elementos dinâmicos sejam renderizados.
                page.wait_for_timeout(
                    2000
                )

                # --------------------------------------------
                # Extrai metadados
                # --------------------------------------------

                metadata = (
                    extract_metadata_from_page(
                        page,
                        record_url,
                    )
                )

                # --------------------------------------------
                # Contadores de qualidade
                # --------------------------------------------

                if not metadata.get(
                    "title"
                ):
                    missing_title += 1

                if not metadata.get(
                    "year"
                ):
                    missing_year += 1

                if not metadata.get(
                    "author"
                ):
                    missing_author += 1

                # --------------------------------------------
                # Salva
                # --------------------------------------------

                output_file = (
                    save_metadata(
                        metadata
                    )
                )

                success += 1

                # --------------------------------------------
                # Log
                # --------------------------------------------

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

            except Exception as error:

                errors += 1

                print(
                    "Erro:",
                    error,
                )

        context.close()
        browser.close()

    # ========================================================
    # RESUMO
    # ========================================================

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

    print(
        "Sem título:",
        missing_title,
    )

    print(
        "Sem ano:",
        missing_year,
    )

    print(
        "Sem autor:",
        missing_author,
    )


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":
    run()