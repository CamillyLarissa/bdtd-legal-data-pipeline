"""
Normalização linguística dos documentos da BDTD.

Entrada:
    data/processed/01_standardized/*.json

Saída:
    data/processed/02_normalized/*.json

Responsabilidades:
- aplicar lematização com spaCy;
- reduzir palavras às formas canônicas;
- preservar tokens em caixa alta;
- preservar siglas, números e tokens especiais;
- manter a estrutura por páginas;
- registrar estatísticas da normalização.

Esta etapa NÃO realiza deduplicação.
"""

import json
import logging
import re

import spacy

from src.config import (
    STANDARDIZED_DIR,
    NORMALIZED_DIR,
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
# SPACY
# ============================================================

MODEL_NAME = "pt_core_news_sm"


def load_nlp():
    """
    Carrega o modelo de português do spaCy.
    """

    try:
        nlp = spacy.load(
            MODEL_NAME,
            disable=[
                "ner",
                "parser",
            ],
        )

        nlp.max_length = 2_000_000

        return nlp

    except OSError as error:
        raise RuntimeError(
            "Modelo pt_core_news_sm não encontrado. "
            "Execute: python -m spacy download pt_core_news_sm"
        ) from error


# ============================================================
# JSON
# ============================================================


def load_json(path):
    with open(
        path,
        "r",
        encoding="utf-8",
    ) as file:
        return json.load(file)


def save_json(path, data):
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
# REGRAS DE PRESERVAÇÃO
# ============================================================


def should_preserve_token(token):
    """
    Define tokens que não devem ser lematizados.

    Preserva:
    - espaços;
    - pontuação;
    - números;
    - URLs;
    - e-mails;
    - tokens totalmente em maiúsculas;
    - siglas;
    - tokens que não possuem caracteres alfabéticos.
    """

    if token.is_space:
        return True

    if token.is_punct:
        return True

    if token.like_num:
        return True

    if token.like_url:
        return True

    if token.like_email:
        return True

    text = token.text

    # Preserva tokens sem letras
    if not re.search(r"[A-Za-zÀ-ÿ]", text):
        return True

    # Preserva palavras totalmente em caixa alta
    # Ex.: STF, STJ, CONCURSO, DIREITOS
    if text.isupper():
        return True

    return False


# ============================================================
# NORMALIZAÇÃO
# ============================================================


def lemmatize_text(text, nlp):
    """
    Aplica lematização conservadora.

    Preserva elementos que podem ser prejudicados pela
    lematização automática, especialmente títulos,
    siglas e elementos jurídicos em caixa alta.
    """

    if not text:
        return ""

    doc = nlp(text)

    parts = []

    for token in doc:
        if token.is_space:
            parts.append(token.text)
            continue

        if should_preserve_token(token):
            normalized_token = token.text

        else:
            lemma = token.lemma_

            if (
                not lemma
                or lemma == "-PRON-"
            ):
                normalized_token = token.text
            else:
                normalized_token = lemma

        parts.append(
            normalized_token
            + token.whitespace_
        )

    return "".join(parts)


def normalize_document(data, nlp):
    """
    Normaliza todas as páginas de um documento.
    """

    document = data.get(
        "document",
        {},
    )

    pages = document.get(
        "pages",
        [],
    )

    normalized_pages = []

    changed_pages = 0
    original_characters = 0
    normalized_characters = 0

    for page in pages:
        original_text = (
            page.get(
                "text",
                "",
            )
            or ""
        )

        normalized_text = (
            lemmatize_text(
                original_text,
                nlp,
            )
        )

        original_characters += len(
            original_text
        )

        normalized_characters += len(
            normalized_text
        )

        if (
            original_text
            != normalized_text
        ):
            changed_pages += 1

        normalized_pages.append(
            {
                "page": page.get("page"),
                "text": normalized_text,
            }
        )

    normalized_data = dict(data)

    normalized_data[
        "document"
    ] = dict(document)

    normalized_data[
        "document"
    ]["pages"] = (
        normalized_pages
    )

    normalized_data[
        "document"
    ][
        "total_characters"
    ] = normalized_characters

    normalized_data[
        "normalization"
    ] = {
        "method": "conservative_lemmatization",
        "library": "spaCy",
        "model": MODEL_NAME,
        "preserve_uppercase": True,
        "preserve_numbers": True,
        "preserve_punctuation": True,
        "preserve_urls": True,
        "changed_pages": (
            changed_pages
        ),
        "original_characters": (
            original_characters
        ),
        "normalized_characters": (
            normalized_characters
        ),
    }

    return normalized_data


# ============================================================
# EXECUÇÃO
# ============================================================


def run():
    create_directories()

    files = sorted(
        STANDARDIZED_DIR.glob(
            "*.json"
        )
    )

    logger.info(
        "Documentos padronizados encontrados: %d",
        len(files),
    )

    if not files:
        logger.warning(
            "Nenhum documento encontrado para normalização."
        )
        return

    logger.info(
        "Carregando modelo spaCy: %s",
        MODEL_NAME,
    )

    nlp = load_nlp()

    success = 0
    errors = 0

    total_changed_pages = 0
    total_original_characters = 0
    total_normalized_characters = 0

    for index, input_file in enumerate(
        files,
        start=1,
    ):
        record_id = input_file.stem

        logger.info(
            "[%d/%d] Normalizando %s",
            index,
            len(files),
            record_id,
        )

        try:
            data = load_json(
                input_file
            )

            normalized_data = (
                normalize_document(
                    data,
                    nlp,
                )
            )

            output_file = (
                NORMALIZED_DIR
                / input_file.name
            )

            save_json(
                output_file,
                normalized_data,
            )

            stats = normalized_data[
                "normalization"
            ]

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

            total_normalized_characters += (
                stats[
                    "normalized_characters"
                ]
            )

            success += 1

            logger.info(
                "Salvo: %s | páginas alteradas=%d | caracteres=%d -> %d",
                output_file,
                stats[
                    "changed_pages"
                ],
                stats[
                    "original_characters"
                ],
                stats[
                    "normalized_characters"
                ],
            )

        except Exception as error:
            errors += 1

            logger.exception(
                "Erro ao normalizar %s: %s",
                record_id,
                error,
            )

    logger.info(
        "=" * 60
    )

    logger.info(
        "NORMALIZAÇÃO FINALIZADA"
    )

    logger.info(
        "Normalizados: %d",
        success,
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
        total_normalized_characters,
    )

    logger.info(
        "Erros: %d",
        errors,
    )


if __name__ == "__main__":
    run()