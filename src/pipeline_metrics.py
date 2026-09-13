import json
from pathlib import Path

import pandas as pd

from src.config import (
    RAW_DIR,
    STAGING_DIR,
    STANDARDIZED_DIR,
    NORMALIZED_DIR,
    DEDUPLICATED_DIR,
    ANONYMIZED_DIR,
    RAG_DIR,
    BENCHMARK_DIR,
)


# ============================================================
# Funções auxiliares
# ============================================================

def percentage(part: int, total: int) -> float:
    """Calcula uma porcentagem com duas casas decimais."""
    if total == 0:
        return 0.0

    return round((part / total) * 100, 2)


def count_json_files(directory: Path) -> int:
    """Conta arquivos JSON existentes no diretório."""
    if not directory.exists():
        return 0

    return len(list(directory.glob("*.json")))


def count_pdf_files(directory: Path) -> int:
    """Conta arquivos PDF existentes no diretório."""
    if not directory.exists():
        return 0

    return len(list(directory.glob("*.pdf")))


def count_document_jsons(directory: Path) -> int:
    """
    Conta somente JSONs correspondentes a documentos.

    Ignora arquivos auxiliares, relatórios e summaries.
    """
    if not directory.exists():
        return 0

    ignored_files = {
        "duplicates.json",
        "summary.json",
        "benchmark_summary.json",
        "benchmark_final_summary.json",
        "rag_summary.json",
        "pipeline_metrics.json",
    }

    return sum(
        1
        for path in directory.glob("*.json")
        if path.name not in ignored_files
    )


def count_jsonl_lines(path: Path) -> int:
    """Conta as linhas válidas de um arquivo JSONL."""
    if not path.exists():
        return 0

    with path.open("r", encoding="utf-8") as file:
        return sum(
            1
            for line in file
            if line.strip()
        )


def count_parquet_rows(path: Path) -> int:
    """Conta quantas linhas existem em um arquivo Parquet."""
    if not path.exists():
        return 0

    try:
        dataframe = pd.read_parquet(path)
        return len(dataframe)

    except Exception as exc:
        print(
            f"Aviso: não foi possível ler o arquivo Parquet "
            f"{path.name}: {exc}"
        )
        return 0


# ============================================================
# Staging
# ============================================================

def staging_has_text(data: dict) -> bool:
    """
    Verifica se um documento da camada Staging possui texto útil.

    Suporta tanto:
    {
        "pages": [...]
    }

    quanto:
    {
        "document": {
            "pages": [...]
        }
    }
    """
    pages = data.get("pages")

    if pages is None:
        document = data.get("document", {})
        pages = document.get("pages", [])

    if not isinstance(pages, list):
        return False

    for page in pages:
        if not isinstance(page, dict):
            continue

        text = (
            page.get("text")
            or page.get("content")
            or ""
        )

        if isinstance(text, str) and text.strip():
            return True

    return False


def count_staging_with_text(directory: Path) -> int:
    """Conta quantos documentos da Staging possuem texto extraído."""
    if not directory.exists():
        return 0

    total = 0

    for path in directory.glob("*.json"):
        try:
            with path.open("r", encoding="utf-8") as file:
                data = json.load(file)

            if staging_has_text(data):
                total += 1

        except Exception:
            # Arquivo com problema não é contabilizado como texto útil.
            continue

    return total


# ============================================================
# Deduplicação
# ============================================================

def count_duplicates(path: Path) -> int:
    """
    Conta os duplicados registrados em duplicates.json.

    Aceita:
    [
        {...},
        {...}
    ]

    ou:
    {
        "duplicates": [...]
    }
    """
    if not path.exists():
        return 0

    try:
        with path.open("r", encoding="utf-8") as file:
            data = json.load(file)

        if isinstance(data, list):
            return len(data)

        if isinstance(data, dict):
            duplicates = data.get("duplicates", [])

            if isinstance(duplicates, list):
                return len(duplicates)

    except Exception as exc:
        print(
            f"Aviso: não foi possível ler duplicates.json: {exc}"
        )

    return 0


# ============================================================
# Pipeline de métricas
# ============================================================

def main():
    # --------------------------------------------------------
    # RAW
    # --------------------------------------------------------

    metadata_dir = RAW_DIR / "metadata" / "records"
    pdf_dir = RAW_DIR / "pdf"

    metadata_count = count_json_files(metadata_dir)
    pdf_count = count_pdf_files(pdf_dir)

    download_rate = percentage(
        pdf_count,
        metadata_count,
    )

    failed_downloads = max(
        metadata_count - pdf_count,
        0,
    )

    # --------------------------------------------------------
    # STAGING
    # --------------------------------------------------------

    staging_processed = count_document_jsons(
        STAGING_DIR
    )

    staging_with_text = count_staging_with_text(
        STAGING_DIR
    )

    staging_without_text = max(
        staging_processed - staging_with_text,
        0,
    )

    text_extraction_rate = percentage(
        staging_with_text,
        pdf_count,
    )

    # --------------------------------------------------------
    # PROCESSED
    # --------------------------------------------------------

    standardized_count = count_document_jsons(
        STANDARDIZED_DIR
    )

    normalized_count = count_document_jsons(
        NORMALIZED_DIR
    )

    deduplicated_count = count_document_jsons(
        DEDUPLICATED_DIR
    )

    anonymized_count = count_document_jsons(
        ANONYMIZED_DIR
    )

    duplicates_file = (
        DEDUPLICATED_DIR / "duplicates.json"
    )

    duplicates_count = count_duplicates(
        duplicates_file
    )

    duplicate_rate = percentage(
        duplicates_count,
        normalized_count,
    )

    deduplication_retention_rate = percentage(
        deduplicated_count,
        normalized_count,
    )

    # --------------------------------------------------------
    # CURATED
    # --------------------------------------------------------

    rag_file = (
        RAG_DIR / "corpus_busca.parquet"
    )

    benchmark_file = (
        BENCHMARK_DIR / "benchmark.jsonl"
    )

    rag_chunks = count_parquet_rows(
        rag_file
    )

    benchmark_questions = count_jsonl_lines(
        benchmark_file
    )

    # --------------------------------------------------------
    # Estrutura final de métricas
    # --------------------------------------------------------

    metrics = {
        "raw": {
            "metadata_records": metadata_count,
            "pdfs_downloaded": pdf_count,
            "failed_downloads": failed_downloads,
            "download_rate_percent": download_rate,
        },

        "staging": {
            "documents_processed": staging_processed,
            "documents_with_text": staging_with_text,
            "documents_without_text": staging_without_text,
            "text_extraction_rate_percent": (
                text_extraction_rate
            ),
        },

        "processed": {
            "standardized": standardized_count,
            "normalized": normalized_count,
            "deduplicated": deduplicated_count,
            "duplicates_found": duplicates_count,
            "duplicate_rate_percent": duplicate_rate,
            "deduplication_retention_percent": (
                deduplication_retention_rate
            ),
            "anonymized": anonymized_count,
        },

        "curated": {
            "rag_chunks": rag_chunks,
            "benchmark_questions": benchmark_questions,
        },
    }

    # --------------------------------------------------------
    # Salvamento
    # --------------------------------------------------------

    output_file = (
        RAW_DIR.parent / "pipeline_metrics.json"
    )

    with output_file.open(
        "w",
        encoding="utf-8",
    ) as file:
        json.dump(
            metrics,
            file,
            ensure_ascii=False,
            indent=2,
        )

    # --------------------------------------------------------
    # Exibição no terminal
    # --------------------------------------------------------

    print()
    print("=" * 60)
    print("MÉTRICAS DO PIPELINE")
    print("=" * 60)

    print()
    print("RAW")
    print("-" * 60)

    print(
        f"Registros coletados: "
        f"{metadata_count}"
    )

    print(
        f"PDFs baixados: "
        f"{pdf_count}"
    )

    print(
        f"Falhas de download: "
        f"{failed_downloads}"
    )

    print(
        f"Taxa de download: "
        f"{download_rate}%"
    )

    print()
    print("STAGING")
    print("-" * 60)

    print(
        f"PDFs processados: "
        f"{staging_processed}"
    )

    print(
        f"Documentos com texto: "
        f"{staging_with_text}"
    )

    print(
        f"Documentos sem texto: "
        f"{staging_without_text}"
    )

    print(
        f"Taxa de extração de texto: "
        f"{text_extraction_rate}%"
    )

    print()
    print("PROCESSED")
    print("-" * 60)

    print(
        f"Padronizados: "
        f"{standardized_count}"
    )

    print(
        f"Normalizados: "
        f"{normalized_count}"
    )

    print(
        f"Documentos únicos: "
        f"{deduplicated_count}"
    )

    print(
        f"Duplicados encontrados: "
        f"{duplicates_count}"
    )

    print(
        f"Taxa de duplicidade: "
        f"{duplicate_rate}%"
    )

    print(
        f"Retenção após deduplicação: "
        f"{deduplication_retention_rate}%"
    )

    print(
        f"Anonimizados: "
        f"{anonymized_count}"
    )

    print()
    print("CURATED")
    print("-" * 60)

    print(
        f"Chunks RAG: "
        f"{rag_chunks}"
    )

    print(
        f"Questões do benchmark: "
        f"{benchmark_questions}"
    )

    print()
    print("=" * 60)

    print(
        f"Métricas salvas em: "
        f"{output_file}"
    )

    print("=" * 60)


# ============================================================
# Execução do script
# ============================================================

if __name__ == "__main__":
    main()