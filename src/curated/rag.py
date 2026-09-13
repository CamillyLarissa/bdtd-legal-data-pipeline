"""
Preparação do dataset Curated para RAG.

Entrada final:
    data/processed/04_anonymized/

Enquanto a anonimização ainda não estiver pronta:
    data/processed/03_deduplicated/

Saídas:
    data/curated/rag/corpus_busca.parquet
    data/curated/rag/rag_summary.json

Cada documento é dividido em chunks de 500 palavras
com overlap de 50 palavras, preservando metadados
contextuais para uso posterior em busca semântica / RAG.
"""

import json
import logging

import pandas as pd

from src.config import (
    ANONYMIZED_DIR,
    DEDUPLICATED_DIR,
    RAG_DIR,
    create_directories,
)


# ============================================================
# CONFIGURAÇÕES
# ============================================================

# Tamanho definido no exemplo prático do slide.
CHUNK_SIZE = 500

# Sobreposição entre chunks consecutivos.
CHUNK_OVERLAP = 50


# ============================================================
# LOG
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)

logger = logging.getLogger(__name__)


# ============================================================
# LEITURA E ESCRITA
# ============================================================

def load_json(path):
    """Carrega um documento JSON."""

    with open(path, "r", encoding="utf-8") as file:
        return json.load(file)


def save_json(path, data):
    """Salva um arquivo JSON."""

    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    with open(path, "w", encoding="utf-8") as file:
        json.dump(
            data,
            file,
            ensure_ascii=False,
            indent=2,
        )


# ============================================================
# ESCOLHA DA CAMADA DE ENTRADA
# ============================================================

def choose_input_directory():
    """
    Usa a camada anonimizada quando houver documentos.

    Enquanto a anonimização ainda não estiver concluída,
    utiliza temporariamente a camada deduplicada.
    """

    anonymized_files = list(
        ANONYMIZED_DIR.glob("*.json")
    )

    if anonymized_files:
        logger.info(
            "Utilizando camada anonimizada: %s",
            ANONYMIZED_DIR,
        )

        return ANONYMIZED_DIR

    logger.warning(
        "Camada anonimizada ainda não disponível. "
        "Utilizando temporariamente: %s",
        DEDUPLICATED_DIR,
    )

    return DEDUPLICATED_DIR


# ============================================================
# CHUNKING
# ============================================================

def split_into_chunks(text):
    """
    Divide o texto em chunks de 500 palavras
    com overlap de 50 palavras.

    O overlap reduz a perda de contexto
    entre o fim de um chunk e o início do próximo.
    """

    words = text.split()

    if not words:
        return []

    chunks = []

    # 500 - 50 = avanço de 450 palavras.
    step = CHUNK_SIZE - CHUNK_OVERLAP

    start = 0

    while start < len(words):

        end = start + CHUNK_SIZE

        chunk_words = words[start:end]

        chunk_text = " ".join(
            chunk_words
        ).strip()

        if chunk_text:
            chunks.append(chunk_text)

        if end >= len(words):
            break

        start += step

    return chunks


# ============================================================
# METADADOS
# ============================================================

def get_value(metadata, *names):
    """
    Procura um valor usando diferentes nomes possíveis.

    Isso ajuda a lidar com pequenas diferenças
    nos metadados vindos dos repositórios da BDTD.
    """

    for name in names:

        value = metadata.get(name)

        if value not in (
            None,
            "",
            [],
        ):
            return value

    return None


def build_chunk(
    record_id,
    metadata,
    page_number,
    chunk_index,
    text,
):
    """
    Cria um chunk autocontido, com texto e
    informações contextuais do documento.
    """

    return {
        "chunk_id": (
            f"{record_id}_p{page_number}_c{chunk_index}"
        ),

        "record_id": record_id,

        "title": get_value(
            metadata,
            "title",
            "titulo",
        ),

        "author": get_value(
            metadata,
            "author",
            "autor",
        ),

        "institution": get_value(
            metadata,
            "institution",
            "instituicao",
            "publisher",
        ),

        "year": get_value(
            metadata,
            "year",
            "ano",
            "date",
        ),

        "page": page_number,

        "chunk_index": chunk_index,

        "text": text,
    }


# ============================================================
# PIPELINE
# ============================================================

def run():
    create_directories()

    input_dir = choose_input_directory()

    files = sorted(
        input_dir.glob("*.json")
    )

    # O relatório de deduplicação não é documento acadêmico.
    files = [
        file
        for file in files
        if file.name != "duplicates.json"
    ]

    logger.info(
        "Documentos encontrados para RAG: %d",
        len(files),
    )

    all_chunks = []

    processed_documents = 0
    skipped_documents = 0
    errors = 0

    # ========================================================
    # PROCESSAMENTO DOS DOCUMENTOS
    # ========================================================

    for index, input_file in enumerate(
        files,
        start=1,
    ):

        record_id = input_file.stem

        logger.info(
            "[%d/%d] Processando %s",
            index,
            len(files),
            record_id,
        )

        try:
            data = load_json(
                input_file
            )

            document = data.get(
                "document",
                {},
            )

            pages = document.get(
                "pages",
                [],
            )

            metadata = data.get(
                "metadata",
                {},
            )

            if not pages:
                logger.warning(
                    "%s não possui páginas.",
                    record_id,
                )

                skipped_documents += 1
                continue

            document_chunks = 0

            # ------------------------------------------------
            # Processamento página por página
            # ------------------------------------------------

            for page_index, page in enumerate(
                pages,
                start=1,
            ):

                text = page.get(
                    "text",
                    "",
                ).strip()

                if not text:
                    continue

                # Preserva o número original da página
                # quando esse dado estiver disponível.
                page_number = page.get(
                    "page_number",
                    page.get(
                        "page",
                        page_index,
                    ),
                )

                chunks = split_into_chunks(
                    text
                )

                for chunk_index, chunk_text in enumerate(
                    chunks,
                    start=1,
                ):

                    chunk = build_chunk(
                        record_id=record_id,
                        metadata=metadata,
                        page_number=page_number,
                        chunk_index=chunk_index,
                        text=chunk_text,
                    )

                    all_chunks.append(
                        chunk
                    )

                    document_chunks += 1

            if document_chunks > 0:
                processed_documents += 1

            else:
                skipped_documents += 1

        except Exception as error:

            errors += 1

            logger.exception(
                "Erro ao processar %s: %s",
                record_id,
                error,
            )

    # ========================================================
    # EXPORTAÇÃO PARA PARQUET
    # ========================================================

    RAG_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    parquet_file = (
        RAG_DIR
        / "corpus_busca.parquet"
    )

    dataframe = pd.DataFrame(
        all_chunks
    )

    dataframe.to_parquet(
        parquet_file,
        index=False,
    )

    # ========================================================
    # RELATÓRIO
    # ========================================================

    summary = {
        "source_directory": str(
            input_dir
        ),

        "chunk_size_words": (
            CHUNK_SIZE
        ),

        "chunk_overlap_words": (
            CHUNK_OVERLAP
        ),

        "documents_found": (
            len(files)
        ),

        "documents_processed": (
            processed_documents
        ),

        "documents_skipped": (
            skipped_documents
        ),

        "total_chunks": (
            len(all_chunks)
        ),

        "errors": (
            errors
        ),

        "output_file": str(
            parquet_file
        ),
    }

    summary_file = (
        RAG_DIR
        / "rag_summary.json"
    )

    save_json(
        summary_file,
        summary,
    )

    # ========================================================
    # RESUMO
    # ========================================================

    logger.info("=" * 60)
    logger.info("DATASET RAG FINALIZADO")

    logger.info(
        "Documentos encontrados: %d",
        len(files),
    )

    logger.info(
        "Documentos processados: %d",
        processed_documents,
    )

    logger.info(
        "Chunks gerados: %d",
        len(all_chunks),
    )

    logger.info(
        "Ignorados: %d",
        skipped_documents,
    )

    logger.info(
        "Erros: %d",
        errors,
    )

    logger.info(
        "Arquivo Parquet: %s",
        parquet_file,
    )


if __name__ == "__main__":
    run()