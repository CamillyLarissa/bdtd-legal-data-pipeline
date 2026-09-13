"""
Preparação do dataset da camada Curated para Pré-Treino Continuado (Continued Pretraining - CPT).

Entrada:
    data/processed/04_anonymized/*.json
    (com fallback para 03_deduplicated, 02_normalized, 01_standardized ou 00_staging se a camada anterior não existir)

Saídas:
    data/curated/pretraining/pretraining_corpus.jsonl
    data/curated/pretraining/pretraining_corpus.txt
    data/curated/pretraining/pretraining_summary.json

Objetivo:
Formatar os documentos processados e anonimizados em arquivos consolidados
de alta qualidade para pré-treino continuado de Grandes Modelos de Linguagem (LLMs)
no domínio do Direito, utilizando delimitadores padrão (<|endoftext|>).
"""

import json
import logging
from pathlib import Path

from src.config import (
    ANONYMIZED_DIR,
    DEDUPLICATED_DIR,
    NORMALIZED_DIR,
    PRETRAINING_DIR,
    STANDARDIZED_DIR,
    STAGING_DIR,
    create_directories,
    env_int,
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
# DELIMITADORES DE PRÉ-TREINO DE LLM
# ============================================================

END_OF_DOC_TOKEN = "<|endoftext|>"


def get_input_directory() -> Path:
    """
    Retorna o diretório de entrada prioritário para o pré-treino continuado.
    Prioridade: ANONYMIZED_DIR > DEDUPLICATED_DIR > NORMALIZED_DIR > STANDARDIZED_DIR > STAGING_DIR
    """
    candidates = [
        ANONYMIZED_DIR,
        DEDUPLICATED_DIR,
        NORMALIZED_DIR,
        STANDARDIZED_DIR,
        STAGING_DIR,
    ]

    for path in candidates:
        if path.exists() and list(path.glob("*.json")):
            valid_files = [f for f in path.glob("*.json") if f.name not in {"duplicates.json", "anonymization_stats.json"}]
            if valid_files:
                logger.info(f"Usando pasta de entrada: {path} ({len(valid_files)} arquivos)")
                return path

    logger.warning("Nenhum diretório com arquivos JSON de entrada encontrado.")
    return ANONYMIZED_DIR


def extract_full_text_from_doc(data: dict) -> tuple[str, int]:
    """
    Concatena o texto de todas as páginas de um documento em uma única string fluida.

    Retorna:
    - texto completo do documento (str)
    - total de páginas (int)
    """
    pages_text = []

    if "pages" in data and isinstance(data["pages"], list):
        for page_info in data["pages"]:
            if isinstance(page_info, dict) and "text" in page_info:
                txt = page_info["text"].strip()
                if txt:
                    pages_text.append(txt)
    elif "text" in data and isinstance(data["text"], str):
        pages_text.append(data["text"].strip())

    full_text = "\n\n".join(pages_text)
    total_pages = len(pages_text)

    return full_text, total_pages


def run(max_files: int | None = None) -> tuple[int, int]:
    """
    Executa o empacotamento dos documentos no formato de dataset para Pré-Treino Continuado.
    """
    create_directories()
    input_dir = get_input_directory()

    if not input_dir.exists():
        logger.warning(f"Diretório de entrada {input_dir} não existe.")
        return 0, 0

    json_files = sorted([
        f for f in input_dir.glob("*.json")
        if f.name not in {"duplicates.json", "anonymization_stats.json"}
    ])

    if not json_files:
        logger.warning(f"Nenhum arquivo JSON encontrado para pré-treino em {input_dir}.")
        return 0, 0

    if max_files and max_files > 0:
        json_files = json_files[:max_files]

    logger.info(f"Iniciando preparação do dataset de pré-treino para {len(json_files)} documentos...")

    PRETRAINING_DIR.mkdir(parents=True, exist_ok=True)

    jsonl_output_file = PRETRAINING_DIR / "pretraining_corpus.jsonl"
    txt_output_file = PRETRAINING_DIR / "pretraining_corpus.txt"
    summary_output_file = PRETRAINING_DIR / "pretraining_summary.json"

    total_docs = 0
    total_words = 0
    total_chars = 0
    total_pages = 0

    success = 0
    errors = 0

    with open(jsonl_output_file, "w", encoding="utf-8") as f_jsonl, \
         open(txt_output_file, "w", encoding="utf-8") as f_txt:

        for index, file_path in enumerate(json_files, start=1):
            record_id = file_path.stem

            try:
                with open(file_path, "r", encoding="utf-8") as f_in:
                    doc_data = json.load(f_in)

                full_text, doc_pages = extract_full_text_from_doc(doc_data)

                if not full_text:
                    logger.warning(f"Documento {record_id} sem texto. Ignorando.")
                    continue

                words_count = len(full_text.split())
                chars_count = len(full_text)

                total_docs += 1
                total_words += words_count
                total_chars += chars_count
                total_pages += doc_pages

                # 1. Escrever no arquivo JSONL
                jsonl_record = {
                    "id": record_id,
                    "text": full_text,
                    "metadata": {
                        "source_pdf": doc_data.get("source_pdf", ""),
                        "total_pages": doc_pages,
                        "word_count": words_count,
                        "char_count": chars_count,
                    }
                }
                f_jsonl.write(json.dumps(jsonl_record, ensure_ascii=False) + "\n")

                # 2. Escrever no arquivo TXT continuo com token de fim de documento
                f_txt.write(full_text + "\n\n" + END_OF_DOC_TOKEN + "\n\n")

                success += 1

                if index % 10 == 0 or index == len(json_files):
                    logger.info(
                        f"[{index}/{len(json_files)}] Empacotado: {record_id} "
                        f"({words_count} palavras, {doc_pages} págs)"
                    )

            except Exception as err:
                errors += 1
                logger.error(f"Erro ao processar {file_path.name} para pré-treino: {err}")

    # Estimativa de tokens para LLMs (aprox. 1 token = 0.75 palavras ou 4 caracteres em português)
    estimated_tokens = int(total_words / 0.75) if total_words > 0 else 0

    summary_data = {
        "total_documents": total_docs,
        "total_pages": total_pages,
        "total_words": total_words,
        "total_characters": total_chars,
        "estimated_tokens": estimated_tokens,
        "files_generated": [
            str(jsonl_output_file.relative_to(PRETRAINING_DIR.parent.parent)),
            str(txt_output_file.relative_to(PRETRAINING_DIR.parent.parent)),
        ],
        "jsonl_size_bytes": jsonl_output_file.stat().st_size if jsonl_output_file.exists() else 0,
        "txt_size_bytes": txt_output_file.stat().st_size if txt_output_file.exists() else 0,
    }

    with open(summary_output_file, "w", encoding="utf-8") as f_sum:
        json.dump(summary_data, f_sum, ensure_ascii=False, indent=2)

    logger.info("=" * 60)
    logger.info("PRÉ-TREINO CONTINUADO (CURATED) FINALIZADO")
    logger.info(f"Documentos empacotados: {total_docs}")
    logger.info(f"Total de Palavras: {total_words:,}")
    logger.info(f"Estimativa de Tokens: {estimated_tokens:,}")
    logger.info(f"Salvo em JSONL: {jsonl_output_file}")
    logger.info(f"Salvo em TXT: {txt_output_file}")
    logger.info(f"Resumo salvo em: {summary_output_file}")

    return success, errors


if __name__ == "__main__":
    max_limit = env_int("PRETRAINING_MAX_FILES", 0)
    limit = max_limit if max_limit > 0 else None
    run(max_files=limit)
