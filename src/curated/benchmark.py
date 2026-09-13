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
MIN_WORDS = int(os.getenv("BDTD_BENCHMARK_MIN_WORDS", "100"))
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
    """Retorna apenas os JSONs correspondentes aos documentos."""
    if not directory.exists():
        return []

    ignored_files = {
        "duplicates.json",
        "candidates.json",
        "benchmark_summary.json",
    }

    return sorted(
        file
        for file in directory.glob("*.json")
        if file.name not in ignored_files
    )


def select_source_directory() -> Path:
    """
    Prioriza a camada anonimizada.
    Enquanto ela não existir, utiliza a deduplicada.
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


def get_pages(data: dict) -> list[dict]:
    """
    Obtém as páginas independentemente de estarem
    no nível principal ou dentro de 'document'.
    """
    pages = data.get("pages")

    if isinstance(pages, list):
        return pages

    document = data.get("document", {})

    if isinstance(document, dict):
        pages = document.get("pages")

        if isinstance(pages, list):
            return pages

    return []


def get_metadata(data: dict) -> dict:
    """
    Obtém os metadados independentemente da posição
    em que estejam armazenados.
    """
    metadata = data.get("metadata")

    if isinstance(metadata, dict):
        return metadata

    document = data.get("document", {})

    if isinstance(document, dict):
        metadata = document.get("metadata")

        if isinstance(metadata, dict):
            return metadata

    return {}


def get_metadata_value(metadata: dict, *keys):
    """Busca o primeiro campo de metadado disponível."""
    for key in keys:
        value = metadata.get(key)

        if value not in (None, "", []):
            return value

    return None


def get_page_number(page: dict):
    """Obtém o número da página considerando nomes diferentes."""
    return (
        page.get("page_number")
        or page.get("page")
        or page.get("number")
    )


def get_page_text(page: dict) -> str:
    """Obtém o conteúdo textual da página."""
    return (
        page.get("text")
        or page.get("content")
        or ""
    ).strip()


def get_valid_pages(pages: list[dict]) -> list[dict]:
    """
    Seleciona páginas com texto suficiente para gerar
    posteriormente perguntas factuais.
    """
    valid_pages = []

    for page in pages:
        text = get_page_text(page)

        if len(text.split()) >= MIN_WORDS:
            valid_pages.append(page)

    if not valid_pages:
        return []

    # Preferência por páginas posteriores à parte pré-textual.
    pages_after_min = []

    for page in valid_pages:
        page_number = get_page_number(page)

        if isinstance(page_number, int) and page_number >= MIN_PAGE:
            pages_after_min.append(page)

    return pages_after_min or valid_pages


def build_candidate(
    data: dict,
    file: Path,
    rng: random.Random,
):
    """Cria um candidato para posterior curadoria humana."""

    pages = get_pages(data)

    if not pages:
        return None

    valid_pages = get_valid_pages(pages)

    if not valid_pages:
        return None

    page = rng.choice(valid_pages)

    metadata = get_metadata(data)

    document = data.get("document", {})

    record_id = (
        data.get("record_id")
        or (
            document.get("record_id")
            if isinstance(document, dict)
            else None
        )
        or metadata.get("record_id")
        or file.stem
    )

    text = get_page_text(page)

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
        "page": get_page_number(page),
        "word_count": len(text.split()),
        "text": text[:MAX_TEXT_CHARS],
    }


# ============================================================
# PROCESSAMENTO PRINCIPAL
# ============================================================

def main():
    BENCHMARK_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    source_dir = select_source_directory()
    files = get_json_files(source_dir)

    logger.info(
        "Documentos disponíveis: %d",
        len(files),
    )

    if not files:
        logger.error(
            "Nenhum documento encontrado."
        )
        return

    rng = random.Random(RANDOM_SEED)

    files = files.copy()
    rng.shuffle(files)

    candidates = []
    ignored = 0
    errors = 0

    for file in files:

        if len(candidates) >= NUM_CANDIDATES:
            break

        try:
            data = load_document(file)

            candidate = build_candidate(
                data,
                file,
                rng,
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

    # ========================================================
    # SALVA CANDIDATOS
    # ========================================================

    candidates_file = (
        BENCHMARK_DIR / "candidates.json"
    )

    with candidates_file.open(
        "w",
        encoding="utf-8",
    ) as f:

        json.dump(
            candidates,
            f,
            ensure_ascii=False,
            indent=2,
        )

    # ========================================================
    # RELATÓRIO
    # ========================================================

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
        "status": "candidate_selection_only",
        "note": (
            "Os candidatos precisam de curadoria humana "
            "para criação das perguntas e dos gabaritos."
        ),
    }

    summary_file = (
        BENCHMARK_DIR / "benchmark_summary.json"
    )

    with summary_file.open(
        "w",
        encoding="utf-8",
    ) as f:

        json.dump(
            summary,
            f,
            ensure_ascii=False,
            indent=2,
        )

    logger.info("=" * 60)
    logger.info(
        "SELEÇÃO DE CANDIDATOS FINALIZADA"
    )
    logger.info(
        "Documentos disponíveis: %d",
        len(files),
    )
    logger.info(
        "Candidatos selecionados: %d",
        len(candidates),
    )
    logger.info(
        "Ignorados: %d",
        ignored,
    )
    logger.info(
        "Erros: %d",
        errors,
    )
    logger.info(
        "Arquivo: %s",
        candidates_file,
    )


if __name__ == "__main__":
    main()