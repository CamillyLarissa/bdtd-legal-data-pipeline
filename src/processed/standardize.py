"""
Padronização dos documentos da BDTD.

Entrada:
    data/staging/*.json
    data/raw/metadata/records/*.json

Saída:
    data/processed/01_standardized/*.json

Responsabilidades:
- unir metadados da BDTD ao texto extraído dos PDFs;
- garantir um esquema uniforme;
- preservar a divisão por páginas;
- aplicar padronização textual:
    * Unicode NFC;
    * remoção de caracteres de controle;
    * limpeza de espaços e tabulações;
    * normalização de quebras de linha;
- identificar documentos sem texto utilizável.

Esta etapa NÃO realiza lematização.
A normalização linguística será feita posteriormente.
"""

import json
import logging
import re
import unicodedata

from src.config import (
    METADATA_DIR,
    STAGING_DIR,
    STANDARDIZED_DIR,
    create_directories,
)


# ============================================================
# LOG
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)

logger = logging.getLogger(__name__)


# ============================================================
# JSON
# ============================================================


def load_json(path):
    """
    Carrega um arquivo JSON.
    """
    with open(
        path,
        "r",
        encoding="utf-8",
    ) as file:
        return json.load(file)


def save_json(path, data):
    """
    Salva dados em JSON UTF-8.
    """
    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    with open(
        path,
        "w",
        encoding="utf-8",
    ) as file:
        json.dump(
            data,
            file,
            ensure_ascii=False,
            indent=2,
        )


# ============================================================
# METADADOS
# ============================================================


def normalize_metadata_value(value):
    """
    Padroniza valores simples de metadados.

    - None permanece None;
    - strings vazias viram None;
    - espaços externos são removidos.
    """

    if value is None:
        return None

    if isinstance(value, str):
        value = value.strip()

        if not value:
            return None

    return value


# ============================================================
# PADRONIZAÇÃO TEXTUAL
# ============================================================


def standardize_text(text):
    """
    Aplica padronização textual de acordo com
    as regras utilizadas na etapa Processed.

    Regras:
    1. Unicode NFC;
    2. remoção de caracteres de controle;
    3. limpeza de espaços e tabs;
    4. normalização de quebras de linha.
    """

    if not text:
        return ""

    # --------------------------------------------------------
    # 1. Unicode NFC
    # --------------------------------------------------------

    text = unicodedata.normalize(
        "NFC",
        text,
    )

    # --------------------------------------------------------
    # 2. Padroniza diferentes quebras de linha
    # --------------------------------------------------------

    text = text.replace(
        "\r\n",
        "\n",
    )

    text = text.replace(
        "\r",
        "\n",
    )

    # --------------------------------------------------------
    # 3. Remove caracteres de controle
    #
    # Mantemos:
    # \n -> quebra de linha
    # \t -> tratado posteriormente
    # --------------------------------------------------------

    text = re.sub(
        r"[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]",
        "",
        text,
    )

    # --------------------------------------------------------
    # 4. Tabs -> espaço
    # --------------------------------------------------------

    text = text.replace(
        "\t",
        " ",
    )

    # --------------------------------------------------------
    # 5. Remove espaços repetidos
    #
    # Não inclui \n, para preservar a estrutura
    # de parágrafos.
    # --------------------------------------------------------

    text = re.sub(
        r" {2,}",
        " ",
        text,
    )

    # --------------------------------------------------------
    # 6. Remove espaços no início/fim de cada linha
    # --------------------------------------------------------

    lines = [
        line.strip()
        for line in text.split("\n")
    ]

    text = "\n".join(lines)

    # --------------------------------------------------------
    # 7. Quebras excessivas
    #
    # Três ou mais quebras consecutivas viram duas.
    # Assim preservamos separação de parágrafos.
    # --------------------------------------------------------

    text = re.sub(
        r"\n{3,}",
        "\n\n",
        text,
    )

    return text.strip()


# ============================================================
# PÁGINAS
# ============================================================


def standardize_pages(pages):
    """
    Padroniza a estrutura e o texto de cada página.
    """

    standardized_pages = []

    changed_pages = 0

    original_characters = 0
    standardized_characters = 0

    for index, page in enumerate(
        pages,
        start=1,
    ):
        page_number = page.get(
            "page",
            index,
        )

        original_text = (
            page.get(
                "text",
                "",
            )
            or ""
        )

        standardized_text = (
            standardize_text(
                original_text
            )
        )

        original_characters += len(
            original_text
        )

        standardized_characters += len(
            standardized_text
        )

        if (
            original_text
            != standardized_text
        ):
            changed_pages += 1

        standardized_pages.append(
            {
                "page": page_number,
                "text": standardized_text,
            }
        )

    stats = {
        "changed_pages": (
            changed_pages
        ),
        "original_characters": (
            original_characters
        ),
        "standardized_characters": (
            standardized_characters
        ),
    }

    return (
        standardized_pages,
        stats,
    )


# ============================================================
# DOCUMENTO
# ============================================================


def standardize_document(
    staging_data,
    metadata,
):
    """
    Une Staging e Raw Metadata em um único
    documento padronizado.
    """

    record_id = staging_data[
        "record_id"
    ]

    pages, stats = (
        standardize_pages(
            staging_data.get(
                "pages",
                [],
            )
        )
    )

    total_characters = (
        stats[
            "standardized_characters"
        ]
    )

    document = {
        "record_id": record_id,

        "source": normalize_metadata_value(
            metadata.get("source")
        ),

        "record_url": normalize_metadata_value(
            metadata.get("record_url")
        ),

        "metadata": {
            "title": normalize_metadata_value(
                metadata.get("title")
            ),

            "year": normalize_metadata_value(
                metadata.get("year")
            ),

            "author": normalize_metadata_value(
                metadata.get("author")
            ),

            "advisor": normalize_metadata_value(
                metadata.get("advisor")
            ),

            "document_type": normalize_metadata_value(
                metadata.get(
                    "document_type"
                )
            ),

            "access_type": normalize_metadata_value(
                metadata.get(
                    "access_type"
                )
            ),

            "language": normalize_metadata_value(
                metadata.get("language")
            ),

            "institution": normalize_metadata_value(
                metadata.get(
                    "institution"
                )
            ),

            "graduate_program": normalize_metadata_value(
                metadata.get(
                    "graduate_program"
                )
            ),

            "department": normalize_metadata_value(
                metadata.get(
                    "department"
                )
            ),

            "country": normalize_metadata_value(
                metadata.get("country")
            ),

            "access_url": normalize_metadata_value(
                metadata.get(
                    "access_url"
                )
            ),

            "abstract": normalize_metadata_value(
                metadata.get("abstract")
            ),
        },

        "document": {
            "total_pages": len(
                pages
            ),

            "total_characters": (
                total_characters
            ),

            "pages": pages,
        },

        "standardization": {
            "unicode_form": "NFC",

            "changed_pages": (
                stats[
                    "changed_pages"
                ]
            ),

            "original_characters": (
                stats[
                    "original_characters"
                ]
            ),

            "standardized_characters": (
                stats[
                    "standardized_characters"
                ]
            ),
        },

        "quality": {
            "has_text": (
                total_characters > 0
            ),
        },
    }

    return document


# ============================================================
# EXECUÇÃO
# ============================================================


def run():
    """
    Executa a padronização dos documentos da
    camada Staging.
    """

    create_directories()

    staging_files = sorted(
        STAGING_DIR.glob(
            "*.json"
        )
    )

    logger.info(
        "Documentos encontrados em Staging: %d",
        len(staging_files),
    )

    success = 0
    skipped_no_text = 0
    missing_metadata = 0
    errors = 0

    total_changed_pages = 0
    total_original_characters = 0
    total_standardized_characters = 0

    for index, staging_file in enumerate(
        staging_files,
        start=1,
    ):
        record_id = (
            staging_file.stem
        )

        logger.info(
            "[%d/%d] Padronizando %s",
            index,
            len(staging_files),
            record_id,
        )

        metadata_file = (
            METADATA_DIR
            / f"{record_id}.json"
        )

        if not metadata_file.exists():
            logger.warning(
                "Metadata não encontrado para %s",
                record_id,
            )

            missing_metadata += 1
            continue

        try:
            staging_data = (
                load_json(
                    staging_file
                )
            )

            metadata = (
                load_json(
                    metadata_file
                )
            )

            document = (
                standardize_document(
                    staging_data,
                    metadata,
                )
            )

            # --------------------------------------------
            # Documento sem texto
            # --------------------------------------------

            if not document[
                "quality"
            ]["has_text"]:

                logger.warning(
                    "%s não possui texto extraído.",
                    record_id,
                )

                skipped_no_text += 1
                continue

            # --------------------------------------------
            # Salva documento
            # --------------------------------------------

            output_file = (
                STANDARDIZED_DIR
                / f"{record_id}.json"
            )

            save_json(
                output_file,
                document,
            )

            stats = (
                document[
                    "standardization"
                ]
            )

            total_changed_pages += (
                stats[
                    "changed_pages"
                ]
            )

            total_original_characters += (
                stats[
                    "original_characters"
                ]
            )

            total_standardized_characters += (
                stats[
                    "standardized_characters"
                ]
            )

            success += 1

            logger.info(
                "Salvo: %s | páginas=%d | alteradas=%d | caracteres=%d -> %d",
                output_file,
                document[
                    "document"
                ]["total_pages"],
                stats[
                    "changed_pages"
                ],
                stats[
                    "original_characters"
                ],
                stats[
                    "standardized_characters"
                ],
            )

        except Exception as error:
            errors += 1

            logger.exception(
                "Erro ao padronizar %s: %s",
                record_id,
                error,
            )

    logger.info(
        "=" * 60
    )

    logger.info(
        "PADRONIZAÇÃO FINALIZADA"
    )

    logger.info(
        "Padronizados: %d",
        success,
    )

    logger.info(
        "Sem texto: %d",
        skipped_no_text,
    )

    logger.info(
        "Metadata ausente: %d",
        missing_metadata,
    )

    logger.info(
        "Páginas alteradas: %d",
        total_changed_pages,
    )

    logger.info(
        "Caracteres antes: %d",
        total_original_characters,
    )

    logger.info(
        "Caracteres depois: %d",
        total_standardized_characters,
    )

    logger.info(
        "Erros: %d",
        errors,
    )


if __name__ == "__main__":
    run()