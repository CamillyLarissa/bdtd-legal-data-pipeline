import json
from pathlib import Path

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

def count_json_files(directory: Path) -> int:
    if not directory.exists():
        return 0
    return len(list(directory.glob("*.json")))


def count_pdf_files(directory: Path) -> int:
    if not directory.exists():
        return 0
    return len(list(directory.glob("*.pdf")))


def count_jsonl_lines(path: Path) -> int:
    if not path.exists():
        return 0

    with path.open("r", encoding="utf-8") as f:
        return sum(1 for line in f if line.strip())


def count_parquet_rows(path: Path) -> int:
    if not path.exists():
        return 0

    try:
        import pandas as pd
        df = pd.read_parquet(path)
        return len(df)
    except Exception:
        return 0


def percentage(part: int, total: int) -> float:
    if total == 0:
        return 0.0
    return round((part / total) * 100, 2)


def main():
    # Raw
    metadata_dir = RAW_DIR / "metadata" / "records"
    pdf_dir = RAW_DIR / "pdf"

    metadata_count = count_json_files(metadata_dir)
    pdf_count = count_pdf_files(pdf_dir)

    # Staging
    staging_count = count_json_files(STAGING_DIR)

    # Processed
    standardized_count = count_json_files(STANDARDIZED_DIR)
    normalized_count = count_json_files(NORMALIZED_DIR)
    deduplicated_count = count_json_files(DEDUPLICATED_DIR)
    anonymized_count = count_json_files(ANONYMIZED_DIR)

    # Duplicados
    duplicates_file = DEDUPLICATED_DIR / "duplicates.json"
    duplicates_count = 0

    if duplicates_file.exists():
        with duplicates_file.open("r", encoding="utf-8") as f:
            data = json.load(f)

        if isinstance(data, list):
            duplicates_count = len(data)
        elif isinstance(data, dict):
            duplicates_count = len(data.get("duplicates", []))

    # Curated
    rag_file = RAG_DIR / "corpus_busca.parquet"
    benchmark_file = BENCHMARK_DIR / "benchmark.jsonl"

    rag_chunks = count_parquet_rows(rag_file)
    benchmark_questions = count_jsonl_lines(benchmark_file)

    metrics = {
        "raw": {
            "metadata_records": metadata_count,
            "pdfs_downloaded": pdf_count,
            "download_rate_percent": percentage(
                pdf_count,
                metadata_count,
            ),
        },
        "staging": {
            "documents_extracted": staging_count,
            "extraction_rate_percent": percentage(
                staging_count,
                pdf_count,
            ),
        },
        "processed": {
            "standardized": standardized_count,
            "normalized": normalized_count,
            "deduplicated": deduplicated_count,
            "duplicates_found": duplicates_count,
            "anonymized": anonymized_count,
            "deduplication_retention_percent": percentage(
                deduplicated_count,
                normalized_count,
            ),
        },
        "curated": {
            "rag_chunks": rag_chunks,
            "benchmark_questions": benchmark_questions,
        },
    }

    output_file = RAW_DIR.parent / "pipeline_metrics.json"

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

    print("=" * 60)
    print("MÉTRICAS DO PIPELINE")
    print("=" * 60)

    print(f"Registros coletados: {metadata_count}")
    print(f"PDFs baixados: {pdf_count}")
    print(
        f"Taxa de download: "
        f"{metrics['raw']['download_rate_percent']}%"
    )

    print()
    print(f"Documentos em Staging: {staging_count}")
    print(
        f"Taxa de extração: "
        f"{metrics['staging']['extraction_rate_percent']}%"
    )

    print()
    print(f"Padronizados: {standardized_count}")
    print(f"Normalizados: {normalized_count}")
    print(f"Deduplicados: {deduplicated_count}")
    print(f"Duplicados encontrados: {duplicates_count}")
    print(f"Anonimizados: {anonymized_count}")

    print()
    print(f"Chunks RAG: {rag_chunks}")
    print(f"Questões benchmark: {benchmark_questions}")

    print()
    print(f"Métricas salvas em: {output_file}")


if __name__ == "__main__":
    main()