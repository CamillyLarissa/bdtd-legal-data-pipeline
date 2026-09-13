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
    """Calcula percentual com duas casas decimais."""
    if total == 0:
        return 0.0

    return round((part / total) * 100, 2)


def count_json_files(directory: Path) -> int:
    """Conta arquivos JSON existentes em um diretório."""
    if not directory.exists():
        return 0

    return len(list(directory.glob("*.json")))


def count_pdf_files(directory: Path) -> int:
    """Conta arquivos PDF existentes em um diretório."""
    if not directory.exists():
        return 0

    return len(list(directory.glob("*.pdf")))


def count_document_jsons(directory: Path) -> int:
    """
    Conta apenas JSONs correspondentes a documentos.

    Arquivos auxiliares, summaries e relatórios não são
    considerados documentos do pipeline.
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
    """Conta instâncias não vazias de um arquivo JSONL."""
    if not path.exists():
        return 0

    with path.open("r", encoding="utf-8") as f:
        return sum(
            1
            for line in f
            if line.strip()
        )


def count_parquet_rows(path: Path) -> int:
    """Conta registros de um arquivo Parquet."""
    if not path.exists():
        return 0

    try:
        dataframe = pd.read_parquet(path)
        return len(dataframe)

    except Exception as exc:
        print(
            f"Aviso: não foi possível ler o Parquet "
            f"{path.name}: {exc}"
        )
        return 0


# ============================================================
# Staging
# ============================================================

def staging_has_text(data: dict) -> bool:
    """
    Verifica se um JSON da camada Staging possui algum texto útil.

    Aceita tanto páginas no nível principal quanto dentro
    da chave 'document'.
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
    """Conta documentos da Staging que possuem texto extraído."""
    if not directory.exists():
        return 0

    total = 0

    for path in directory.glob("*.json"):
        try:
            with path.open(
                "r",
                encoding="utf-8",
            ) as f:
                data = json.load(f)

            if staging_has_text(data):
                total += 1

        except Exception:
            # Arquivo problemático não é contado como texto útil.
            continue

    return total


# ============================================================
# Deduplicação
# ============================================================

def count_duplicates(path: Path) -> int:
    """
    Conta duplicados registrados no arquivo duplicates.json.

    Aceita tanto uma lista direta quanto um dicionário
    contendo a chave 'duplicates'.
    """
    if not path.exists():
        return 0

    try:
        with path.open(
            "r",
            encoding="utf-8",
        ) as f:
            data = json.load(f)

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
# Métricas
# ============================================================

def main():
    # --------------------------------------------------------
    # Raw
    # --------------------------------------------------------

    metadata_dir = RAW_DIR / "metadata" / "records"
    pdf_dir = RAW_DIR / "pdf"

    metadata_count = count_json_files(metadata_dir)
    pdf_count = count_pdf_files(pdf_dir)

    download_rate = percentage(
        pdf_count,
        metadata_count,
    )

    # --------------------------------------------------------
    # Staging
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
    # Processed
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

    deduplication_retention_rate = percentage(
        deduplicated_count,
        normalized_count,
    )

    duplicate_rate = percentage(
        duplicates_count,
        normalized_count,
    )

    # --------------------------------------------------------
    # Curated
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
    # Métricas consolidadas
    # --------------------------------------------------------

    metrics = {
        "raw": {
            "metadata_records": metadata_count,
            "pdfs_downloaded": pdf_count,
            "download_rate_percent": download_rate,
        },

        "staging": {
            "documents_processed": staging_processed,
            "documents_with_text": staging_with_text,
            "documents_without_text": staging_without_text,
            "text_extraction_rate_percent": text_extraction_rate,
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
    ) as f:
        json.dump(
            metrics,
            f,
            ensure_ascii=False,
            indent=2,
        )

    # --------------------------------------------------------
    # Resultado no terminal
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


if __name__ == "__main__":
    main()