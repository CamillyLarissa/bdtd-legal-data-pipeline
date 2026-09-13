import json
import logging
import os
import random
from pathlib import Path

from src.config import (
    ANONYMIZED_DIR,
    DEDUPLICATED_DIR,
    BENCHMARK_DIR,
)


# ============================================================
# CONFIGURAÇÕES
# ============================================================

NUM_CANDIDATES = int(os.getenv("BDTD_BENCHMARK_CANDIDATES", "10"))
MIN_WORDS = int(os.getenv("BDTD_BENCHMARK_MIN_WORDS", "150"))
MIN_PAGE = int(os.getenv("BDTD_BENCHMARK_MIN_PAGE", "5"))
MAX_TEXT_CHARS = int(os.getenv("BDTD_BENCHMARK_MAX_CHARS", "2500"))
RANDOM_SEED = int(os.getenv("BDTD_BENCHMARK_SEED", "42"))


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)

logger = logging.getLogger(__name__)


# ============================================================
# FUNÇÕES AUXILIARES
# ============================================================

def get_json_files(directory: Path) -> list[Path]:
    """
    Retorna somente os arquivos JSON correspondentes aos documentos.
    Arquivos auxiliares, como duplicates.json, são ignorados.
    """
    if not directory.exists():
        return []

    return sorted(
        file
        for file in directory.glob("*.json")
        if file.name not in {
            "duplicates.json",
            "candidates.json",
            "benchmark_summary.json",
        }
    )


def select_source_directory() -> Path:
    """
    Usa a camada anonimizada quando ela estiver disponível.

    Enquanto a anonimização ainda não tiver sido concluída,
    utiliza temporariamente a camada deduplicada.
    """
    anonymized_files = get_json_files(ANONYMIZED_DIR)

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


def load_document(file: Path) -> dict:
    """Carrega um documento JSON."""
    with file.open("r", encoding="utf-8") as f:
        return json.load(f)


def get_metadata_value(metadata: dict, *keys):
    """
    Tenta obter um valor utilizando diferentes nomes de campo.
    Isso ajuda quando metadados de diferentes repositórios
    possuem pequenas variações.
    """
    for key in keys:
        value = metadata.get(key)

        if value not in (None, "", []):
            return value

    return None


def get_valid_pages(pages: list[dict]) -> list[dict]:
    """
    Seleciona páginas com quantidade suficiente de texto.

    Preferimos páginas a partir da página 5 para reduzir a
    probabilidade de selecionar capas, fichas catalográficas
    ou páginas iniciais.
    """
    valid_pages = []

    for page in pages:
        text = page.get("text", "").strip()

        if len(text.split()) < MIN_WORDS:
            continue

        valid_pages.append(page)

    if not valid_pages:
        return []

    pages_after_min = [
        page
        for page in valid_pages
        if page.get("page_number", 0) >= MIN_PAGE
    ]

    # Caso não haja páginas >= MIN_PAGE, mantém as páginas válidas.
    return pages_after_min or valid_pages


def build_candidate(document: dict, file: Path, rng: random.Random):
    """
    Seleciona uma página adequada do documento e gera
    uma instância candidata para futura curadoria humana.
    """
    pages = document.get("pages", [])
    valid_pages = get_valid_pages(pages)

    if not valid_pages:
        return None

    page = rng.choice(valid_pages)

    metadata = document.get("metadata", {})

    record_id = (
        document.get("record_id")
        or metadata.get("record_id")
        or file.stem
    )

    text = page.get("text", "").strip()

    return {
        "record_id": record_id,
        "title": get_metadata_value(
            metadata,
            "title",
            "titulo",
        ),
        "author": get_metadata_value(
            metadata,
            "author",
            "autor",
            "creator",
        ),
        "institution": get_metadata_value(
            metadata,
            "institution",
            "instituicao",
            "publisher",
        ),
        "year": get_metadata_value(
            metadata,
            "year",
            "ano",
            "date",
        ),
        "page": page.get("page_number"),
        "word_count": len(text.split()),
        "text": text[:MAX_TEXT_CHARS],
    }


# ============================================================
# PROCESSAMENTO PRINCIPAL
# ============================================================

def main():
    BENCHMARK_DIR.mkdir(parents=True, exist_ok=True)

    source_dir = select_source_directory()
    files = get_json_files(source_dir)

    logger.info("Documentos disponíveis: %d", len(files))

    if not files:
        logger.error("Nenhum documento encontrado.")
        return

    rng = random.Random(RANDOM_SEED)

    # Embaralhamento determinístico para permitir reprodução.
    files = files.copy()
    rng.shuffle(files)

    candidates = []
    ignored = 0
    errors = 0

    for file in files:
        if len(candidates) >= NUM_CANDIDATES:
            break

        try:
            document = load_document(file)

            candidate = build_candidate(
                document=document,
                file=file,
                rng=rng,
            )

            if candidate is None:
                ignored += 1
                logger.warning(
                    "Documento sem página adequada: %s",
                    file.stem,
                )
                continue

            candidates.append(candidate)

            logger.info(
                "[%d/%d] Candidato selecionado: %s - página %s",
                len(candidates),
                NUM_CANDIDATES,
                candidate["record_id"],
                candidate["page"],
            )

        except Exception as exc:
            errors += 1

            logger.exception(
                "Erro ao processar %s: %s",
                file.name,
                exc,
            )

    # --------------------------------------------------------
    # Salva candidatos
    # --------------------------------------------------------

    candidates_file = BENCHMARK_DIR / "candidates.json"

    with candidates_file.open("w", encoding="utf-8") as f:
        json.dump(
            candidates,
            f,
            ensure_ascii=False,
            indent=2,
        )

    # --------------------------------------------------------
    # Relatório da etapa
    # --------------------------------------------------------

    summary = {
        "source_directory": str(source_dir),
        "documents_available": len(files),
        "candidates_requested": NUM_CANDIDATES,
        "candidates_selected": len(candidates),
        "ignored": ignored,
        "errors": errors,
        "selection": {
            "minimum_words_per_page": MIN_WORDS,
            "preferred_minimum_page": MIN_PAGE,
            "maximum_text_characters": MAX_TEXT_CHARS,
            "random_seed": RANDOM_SEED,
        },
        "status": (
            "candidate_selection_only"
        ),
        "note": (
            "Os candidatos ainda precisam de curadoria humana "
            "para criação das perguntas e respectivos gabaritos."
        ),
    }

    summary_file = BENCHMARK_DIR / "benchmark_summary.json"

    with summary_file.open("w", encoding="utf-8") as f:
        json.dump(
            summary,
            f,
            ensure_ascii=False,
            indent=2,
        )

    logger.info("=" * 60)
    logger.info("SELEÇÃO DE CANDIDATOS FINALIZADA")
    logger.info("Documentos disponíveis: %d", len(files))
    logger.info("Candidatos selecionados: %d", len(candidates))
    logger.info("Ignorados: %d", ignored)
    logger.info("Erros: %d", errors)
    logger.info("Arquivo: %s", candidates_file)


if __name__ == "__main__":
    main()