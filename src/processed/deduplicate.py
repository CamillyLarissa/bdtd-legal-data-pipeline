"""
Deduplicação dos documentos normalizados da BDTD.

Entrada:
    data/processed/02_normalized/*.json

Saída:
    data/processed/03_deduplicated/*.json
    data/processed/03_deduplicated/duplicates.json

Estratégia:
1. Gerar shingles de palavras.
2. Criar uma assinatura MinHash para cada documento.
3. Usar LSH para buscar candidatos semelhantes.
4. Confirmar a similaridade com Jaccard.
5. Manter documentos únicos e registrar duplicatas.
"""

import json
import logging
import re

from datasketch import MinHash, MinHashLSH

from src.config import (
    NORMALIZED_DIR,
    DEDUPLICATED_DIR,
    create_directories,
)


# ============================================================
# CONFIGURAÇÕES
# ============================================================

# Quantidade de funções usadas na assinatura MinHash.
NUM_PERM = 128

# Cada shingle será formado por 5 palavras consecutivas.
SHINGLE_SIZE = 5

# Similaridade mínima para considerar dois documentos duplicados.
SIMILARITY_THRESHOLD = 0.80


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
    """Carrega um arquivo JSON."""

    with open(path, "r", encoding="utf-8") as file:
        return json.load(file)


def save_json(path, data):
    """Salva um arquivo JSON."""

    path.parent.mkdir(parents=True, exist_ok=True)

    with open(path, "w", encoding="utf-8") as file:
        json.dump(
            data,
            file,
            ensure_ascii=False,
            indent=2,
        )


# ============================================================
# PREPARAÇÃO DO TEXTO
# ============================================================

def get_document_text(data):
    """
    Junta o texto de todas as páginas do documento,
    mantendo a ordem original.
    """

    pages = data.get("document", {}).get("pages", [])

    return "\n".join(
        page.get("text", "")
        for page in pages
        if page.get("text")
    )


def generate_shingles(text):
    """
    Divide o documento em conjuntos de 5 palavras consecutivas.

    Exemplo:
        "direito penal brasileiro contemporâneo atual"

    gera:
        "direito penal brasileiro contemporâneo atual"

    Com textos maiores, a janela avança uma palavra por vez.
    """

    # Caixa baixa evita que diferenças apenas de maiúsculas
    # produzam shingles diferentes.
    tokens = re.findall(
        r"\b\w+\b",
        text.lower(),
        flags=re.UNICODE,
    )

    if not tokens:
        return set()

    # Caso o texto tenha menos palavras que SHINGLE_SIZE,
    # todo o conteúdo vira um único shingle.
    if len(tokens) < SHINGLE_SIZE:
        return {" ".join(tokens)}

    return {
        " ".join(tokens[i:i + SHINGLE_SIZE])
        for i in range(len(tokens) - SHINGLE_SIZE + 1)
    }


# ============================================================
# MINHASH
# ============================================================

def create_minhash(shingles):
    """
    Cria uma assinatura compacta MinHash.

    Em vez de comparar documentos completos,
    o LSH utiliza essas assinaturas para localizar
    candidatos potencialmente semelhantes.
    """

    minhash = MinHash(num_perm=NUM_PERM)

    for shingle in shingles:
        minhash.update(
            shingle.encode("utf-8")
        )

    return minhash


# ============================================================
# SIMILARIDADE
# ============================================================

def jaccard_similarity(a, b):
    """
    Calcula a similaridade de Jaccard real entre
    os conjuntos de shingles.

    J(A,B) = interseção / união
    """

    if not a or not b:
        return 0.0

    return len(a & b) / len(a | b)


# ============================================================
# DEDUPLICAÇÃO
# ============================================================

def run():
    create_directories()

    files = sorted(
        NORMALIZED_DIR.glob("*.json")
    )

    logger.info(
        "Documentos normalizados encontrados: %d",
        len(files),
    )

    if not files:
        logger.warning(
            "Nenhum documento encontrado."
        )
        return

    # Índice responsável por localizar rapidamente
    # documentos potencialmente semelhantes.
    lsh = MinHashLSH(
        threshold=SIMILARITY_THRESHOLD,
        num_perm=NUM_PERM,
    )

    # Guardamos os shingles dos documentos já aceitos
    # para posteriormente confirmar a similaridade.
    stored_shingles = {}

    duplicates = []

    unique_count = 0
    duplicate_count = 0
    errors = 0

    for index, input_file in enumerate(files, start=1):

        record_id = input_file.stem

        logger.info(
            "[%d/%d] Verificando %s",
            index,
            len(files),
            record_id,
        )

        try:
            data = load_json(input_file)

            text = get_document_text(data)

            if not text.strip():
                logger.warning(
                    "%s não possui texto utilizável.",
                    record_id,
                )
                continue

            # ------------------------------------------------
            # 1. Shingles
            # ------------------------------------------------

            shingles = generate_shingles(text)

            # ------------------------------------------------
            # 2. Assinatura MinHash
            # ------------------------------------------------

            minhash = create_minhash(shingles)

            # ------------------------------------------------
            # 3. LSH retorna apenas candidatos prováveis
            # ------------------------------------------------

            candidates = lsh.query(minhash)

            duplicate_of = None
            best_similarity = 0.0

            # ------------------------------------------------
            # 4. Confirma candidatos usando Jaccard
            # ------------------------------------------------

            for candidate_id in candidates:

                similarity = jaccard_similarity(
                    shingles,
                    stored_shingles[candidate_id],
                )

                if similarity > best_similarity:
                    best_similarity = similarity

                if similarity >= SIMILARITY_THRESHOLD:
                    duplicate_of = candidate_id
                    break

            # ------------------------------------------------
            # Documento duplicado
            # ------------------------------------------------

            if duplicate_of:

                duplicate_count += 1

                duplicates.append(
                    {
                        "duplicate_record_id": record_id,
                        "original_record_id": duplicate_of,
                        "similarity": round(
                            best_similarity,
                            4,
                        ),
                    }
                )

                logger.warning(
                    "Duplicado: %s -> %s | similaridade=%.4f",
                    record_id,
                    duplicate_of,
                    best_similarity,
                )

                continue

            # ------------------------------------------------
            # Documento único
            # ------------------------------------------------

            # Somente documentos únicos entram no índice.
            # Os próximos documentos serão comparados com eles.
            lsh.insert(
                record_id,
                minhash,
            )

            stored_shingles[
                record_id
            ] = shingles

            # Adiciona informações sobre a deduplicação
            # ao próprio documento.
            data["deduplication"] = {
                "method": "minhash_lsh_jaccard",
                "shingle_size": SHINGLE_SIZE,
                "num_perm": NUM_PERM,
                "similarity_threshold": SIMILARITY_THRESHOLD,
                "is_duplicate": False,
            }

            output_file = (
                DEDUPLICATED_DIR
                / input_file.name
            )

            save_json(
                output_file,
                data,
            )

            unique_count += 1

        except Exception as error:

            errors += 1

            logger.exception(
                "Erro ao processar %s: %s",
                record_id,
                error,
            )

    # ========================================================
    # RELATÓRIO
    # ========================================================

    report = {
        "method": "minhash_lsh_jaccard",

        "configuration": {
            "shingle_size": SHINGLE_SIZE,
            "num_perm": NUM_PERM,
            "similarity_threshold": SIMILARITY_THRESHOLD,
        },

        "total_input": len(files),
        "unique_documents": unique_count,
        "duplicate_documents": duplicate_count,
        "errors": errors,

        "duplicates": duplicates,
    }

    report_file = (
        DEDUPLICATED_DIR
        / "duplicates.json"
    )

    save_json(
        report_file,
        report,
    )

    # ========================================================
    # RESUMO
    # ========================================================

    logger.info("=" * 60)
    logger.info("DEDUPLICAÇÃO FINALIZADA")

    logger.info(
        "Entrada: %d",
        len(files),
    )

    logger.info(
        "Documentos únicos: %d",
        unique_count,
    )

    logger.info(
        "Duplicados encontrados: %d",
        duplicate_count,
    )

    logger.info(
        "Erros: %d",
        errors,
    )

    logger.info(
        "Relatório salvo em: %s",
        report_file,
    )


if __name__ == "__main__":
    run()