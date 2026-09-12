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
- identificar documentos sem texto utilizável.

Esta etapa NÃO altera linguisticamente o texto.
A normalização é realizada em normalize.py.
"""

import json
import logging

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
# UTILITÁRIOS
# ============================================================


def normalize_metadata_value(value):
    """
    Padroniza valores de metadados sem alterar
    semanticamente seu conteúdo.

    - None vira null no JSON;
    - strings vazias viram null;
    - espaços externos são removidos.
    """

    if value is None:
        return None

    if isinstance(value, str):
        value = value.strip()

        if not value:
            return None

    return value


def count_characters(pages):
    """
    Conta a quantidade total de caracteres
    extraídos do documento.
    """

    return sum(
        len(page.get("text", ""))
        for page in pages
    )


def standardize_pages(pages):
    """
    Garante que todas as páginas tenham
    a mesma estrutura.

    O texto ainda não é normalizado.
    """

    standardized_pages = []

    for index, page in enumerate(
        pages,
        start=1,
    ):
        page_number = page.get(
            "page",
            index,
        )

        text = page.get(
            "text",
            "",
        )

        if text is None:
            text = ""

        standardized_pages.append(
            {
                "page": page_number,
                "text": str(text),
            }
        )

    return standardized_pages


# ============================================================
# PADRONIZAÇÃO
# ============================================================


def standardize_document(
    staging_data,
    metadata,
):
    """
    Une Staging e Raw Metadata em um único
    esquema padronizado.
    """

    record_id = staging_data[
        "record_id"
    ]

    pages = standardize_pages(
        staging_data.get(
            "pages",
            [],
        )
    )

    total_characters = (
        count_characters(pages)
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
            "total_pages": len(pages),
            "total_characters": (
                total_characters
            ),
            "pages": pages,
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
    Executa a padronização de todos os documentos
    presentes na camada Staging.
    """

    create_directories()

    staging_files = sorted(
        STAGING_DIR.glob("*.json")
    )

    logger.info(
        "Documentos encontrados em Staging: %d",
        len(staging_files),
    )

    success = 0
    skipped_no_text = 0
    missing_metadata = 0
    errors = 0

    for index, staging_file in enumerate(
        staging_files,
        start=1,
    ):
        record_id = staging_file.stem

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
            staging_data = load_json(
                staging_file
            )

            metadata = load_json(
                metadata_file
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

            success += 1

            logger.info(
                "Salvo: %s | páginas=%d | caracteres=%d",
                output_file,
                document[
                    "document"
                ]["total_pages"],
                document[
                    "document"
                ]["total_characters"],
            )

        except Exception as error:
            errors += 1

            logger.exception(
                "Erro ao padronizar %s: %s",
                record_id,
                error,
            )

    logger.info("=" * 60)
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
        "Erros: %d",
        errors,
    )


if __name__ == "__main__":
    run()