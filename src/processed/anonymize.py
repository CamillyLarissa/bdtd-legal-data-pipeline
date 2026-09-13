"""
Anonimização de dados sensíveis e pessoais (PII) nos documentos da BDTD.

Entrada:
    data/processed/03_deduplicated/*.json
    (com fallback para 02_normalized, 01_standardized ou data/staging se 03_deduplicated não existir)

Saída:
    data/processed/04_anonymized/*.json
    data/processed/04_anonymized/anonymization_stats.json

Estratégia Híbrida de Anonimização:
- Nível 1 (Determinístico / Regex): CPFs, CNPJs, E-mails, Telefones, OAB, Processos CNJ, RGs, CEPs, Endereços.
- Nível 2 (Probabilístico / NER com spaCy - Opcional): Reconhecimento de Entidades Nomeadas (PER)
  ativado via variável de ambiente ANONYMIZE_USE_NER=true (suportado nativamente no Google Colab).
"""

import json
import logging
import os
import re
from pathlib import Path

from src.config import (
    ANONYMIZED_DIR,
    DEDUPLICATED_DIR,
    NORMALIZED_DIR,
    STANDARDIZED_DIR,
    STAGING_DIR,
    create_directories,
    env_bool,
    env_int,
)

# ============================================================
# TENTATIVA DE CARREGAMENTO DO SPACY (NÍVEL 2 - NER)
# ============================================================

SPACY_NLP = None
try:
    import spacy
    try:
        SPACY_NLP = spacy.load("pt_core_news_sm")
    except Exception:
        # Tenta modelo alternativo se pt_core_news_sm não estiver baixado
        try:
            SPACY_NLP = spacy.load("pt_core_news_lg")
        except Exception:
            SPACY_NLP = None
except ImportError:
    SPACY_NLP = None


# ============================================================
# LOG
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)

logger = logging.getLogger(__name__)


# ============================================================
# PADRÕES REGEX PARA ANONIMIZAÇÃO (NÍVEL 1)
# ============================================================

# Padrão CNJ para Número de Processo Judicial: NNNNNNN-DD.AAAA.J.TR.OOOO
REGEX_PROCESSO_CNJ = re.compile(
    r"\b\d{7}-\d{2}\.\d{4}\.\d\.\d{2}\.\d{4}\b"
)

# CPF: 000.000.000-00
REGEX_CPF = re.compile(
    r"\b\d{3}\.\d{3}\.\d{3}-\d{2}\b"
)

# CNPJ: 00.000.000/0000-00
REGEX_CNPJ = re.compile(
    r"\b\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}\b"
)

# Endereços de e-mail
REGEX_EMAIL = re.compile(
    r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"
)

# Números de telefone
REGEX_TELEFONE = re.compile(
    r"(?:\+?55\s?)?(?:\(?\d{2}\)?\s?)(?:9?\d{4}[-.\s]?\d{4})\b"
)

# Registro OAB
REGEX_OAB = re.compile(
    r"\bOAB(?:/[A-Z]{2}|-[A-Z]{2}|\s+[A-Z]{2})\s?\d{3,6}\b",
    re.IGNORECASE,
)

# RG / Documento de Identidade em contexto
REGEX_RG = re.compile(
    r"\b(?:RG|R\.G\.)\s*(?:nº|nº\.|num|número)?\s*[\d\.\-]{5,14}\b",
    re.IGNORECASE,
)

# CEP: 00000-000
REGEX_CEP = re.compile(
    r"\b\d{5}-\d{3}\b"
)

# Endereço residencial em contexto
REGEX_ENDERECO = re.compile(
    r"\b(?:Rua|Av\.|Avenida|Alameda|Praça|Servidão)\s+[A-ZÀ-Úa-zà-ú0-9\s]{3,35},\s*nº?\s*\d+\b",
    re.IGNORECASE,
)

# Data de nascimento em contexto
REGEX_DATA_NASC = re.compile(
    r"\b(?:nascido\(a\)|nascido em|data de nascimento:?)\s*\d{2}/\d{2}/\d{4}\b",
    re.IGNORECASE,
)


def anonymize_text(text: str, use_ner: bool = False) -> tuple[str, dict[str, int]]:
    """
    Substitui padrões de PII por tokens genéricos de anonimização no texto.

    Retorna:
    - texto anonimizado (str)
    - contagem de substituições realizadas por categoria (dict)
    """
    if not text:
        return text, {}

    stats = {
        "cpf": 0,
        "cnpj": 0,
        "email": 0,
        "telefone": 0,
        "processo_cnj": 0,
        "oab": 0,
        "rg": 0,
        "cep": 0,
        "endereco": 0,
        "data_nascimento": 0,
        "ner_pessoas": 0,
    }

    # ------------------------------------------------------------
    # NÍVEL 1: REGEX (DETERMINÍSTICO)
    # ------------------------------------------------------------

    text, count = REGEX_PROCESSO_CNJ.subn("[PROCESSO_ANONIMIZADO]", text)
    stats["processo_cnj"] += count

    text, count = REGEX_CPF.subn("[CPF_ANONIMIZADO]", text)
    stats["cpf"] += count

    text, count = REGEX_CNPJ.subn("[CNPJ_ANONIMIZADO]", text)
    stats["cnpj"] += count

    text, count = REGEX_EMAIL.subn("[EMAIL_ANONIMIZADO]", text)
    stats["email"] += count

    text, count = REGEX_OAB.subn("[OAB_ANONIMIZADO]", text)
    stats["oab"] += count

    text, count = REGEX_RG.subn("[RG_ANONIMIZADO]", text)
    stats["rg"] += count

    text, count = REGEX_CEP.subn("[CEP_ANONIMIZADO]", text)
    stats["cep"] += count

    text, count = REGEX_ENDERECO.subn("[ENDERECO_ANONIMIZADO]", text)
    stats["endereco"] += count

    text, count = REGEX_DATA_NASC.subn("[DATA_NASC_ANONIMIZADA]", text)
    stats["data_nascimento"] += count

    text, count = REGEX_TELEFONE.subn("[TELEFONE_ANONIMIZADO]", text)
    stats["telefone"] += count

    # ------------------------------------------------------------
    # NÍVEL 2: NER COM SPACY (PROBABILÍSTICO - OPCIONAL)
    # ------------------------------------------------------------
    if use_ner and SPACY_NLP is not None:
        try:
            doc = SPACY_NLP(text[:50000])  # Limite por segurança de memória
            per_entities = [ent.text for ent in doc.ents if ent.label_ == "PER" and len(ent.text) > 3]
            for name in set(per_entities):
                # Substitui apenas nomes com mais de uma palavra para evitar falso positivo em palavras isoladas
                if " " in name:
                    text = text.replace(name, "[PESSOA_ANONIMIZADA]")
                    stats["ner_pessoas"] += 1
        except Exception as e:
            logger.debug(f"Erro na execução do NER spaCy: {e}")

    return text, stats


def get_input_directory() -> Path:
    """
    Retorna o diretório de entrada prioritário para a anonimização.
    Prioridade: DEDUPLICATED_DIR > NORMALIZED_DIR > STANDARDIZED_DIR > STAGING_DIR
    """
    candidates = [
        DEDUPLICATED_DIR,
        NORMALIZED_DIR,
        STANDARDIZED_DIR,
        STAGING_DIR,
    ]

    for path in candidates:
        if path.exists() and list(path.glob("*.json")):
            valid_files = [f for f in path.glob("*.json") if f.name != "duplicates.json"]
            if valid_files:
                logger.info(f"Usando pasta de entrada: {path} ({len(valid_files)} arquivos)")
                return path

    logger.warning("Nenhum diretório com arquivos JSON de entrada encontrado.")
    return DEDUPLICATED_DIR


def anonymize_document(data: dict, use_ner: bool = False) -> tuple[dict, dict[str, int]]:
    """
    Aplica a anonimização em todos os campos textuais de um documento JSON.
    """
    total_stats = {
        "cpf": 0,
        "cnpj": 0,
        "email": 0,
        "telefone": 0,
        "processo_cnj": 0,
        "oab": 0,
        "rg": 0,
        "cep": 0,
        "endereco": 0,
        "data_nascimento": 0,
        "ner_pessoas": 0,
    }

    anonymized_data = data.copy()

    # 1. Anonimizar páginas de texto
    if "pages" in anonymized_data and isinstance(anonymized_data["pages"], list):
        new_pages = []
        for page_info in anonymized_data["pages"]:
            if isinstance(page_info, dict) and "text" in page_info:
                text_anon, page_stats = anonymize_text(page_info["text"], use_ner=use_ner)
                for k, v in page_stats.items():
                    total_stats[k] += v

                new_page = page_info.copy()
                new_page["text"] = text_anon
                new_pages.append(new_page)
            else:
                new_pages.append(page_info)
        anonymized_data["pages"] = new_pages

    # 2. Anonimizar resumo / abstract / título se existirem em metadados
    for field in ["resumo", "abstract", "title", "titulo"]:
        if field in anonymized_data and isinstance(anonymized_data[field], str):
            anon_val, field_stats = anonymize_text(anonymized_data[field], use_ner=use_ner)
            for k, v in field_stats.items():
                total_stats[k] += v
            anonymized_data[field] = anon_val

    return anonymized_data, total_stats


def run(max_files: int | None = None, use_ner: bool | None = None) -> tuple[int, int]:
    """
    Executa a etapa de anonimização para todos os documentos da camada Processed.
    """
    create_directories()
    input_dir = get_input_directory()

    if use_ner is None:
        use_ner = env_bool("ANONYMIZE_USE_NER", False)

    if use_ner and SPACY_NLP is None:
        logger.info("ANONYMIZE_USE_NER=true, mas spaCy/modelo pt_core_news não instalado. Executando Nível 1 (Regex).")
        use_ner = False
    elif use_ner:
        logger.info("Anonimização Nível 2 (NER com spaCy) ATIVADA.")

    if not input_dir.exists():
        logger.warning(f"Diretório de entrada {input_dir} não existe.")
        return 0, 0

    json_files = sorted([f for f in input_dir.glob("*.json") if f.name != "duplicates.json"])

    if not json_files:
        logger.warning(f"Nenhum arquivo JSON para anonimizar em {input_dir}.")
        return 0, 0

    if max_files and max_files > 0:
        json_files = json_files[:max_files]

    logger.info(f"Iniciando anonimização de {len(json_files)} documentos...")

    ANONYMIZED_DIR.mkdir(parents=True, exist_ok=True)

    success = 0
    errors = 0

    global_stats = {
        "total_documents": len(json_files),
        "anonymized_documents": 0,
        "total_replacements": 0,
        "ner_enabled": use_ner,
        "replacements_by_type": {
            "cpf": 0,
            "cnpj": 0,
            "email": 0,
            "telefone": 0,
            "processo_cnj": 0,
            "oab": 0,
            "rg": 0,
            "cep": 0,
            "endereco": 0,
            "data_nascimento": 0,
            "ner_pessoas": 0,
        },
    }

    for index, file_path in enumerate(json_files, start=1):
        record_id = file_path.stem

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            anon_data, doc_stats = anonymize_document(data, use_ner=use_ner)

            doc_total_replacements = sum(doc_stats.values())
            if doc_total_replacements > 0:
                global_stats["anonymized_documents"] += 1
                global_stats["total_replacements"] += doc_total_replacements
                for k, v in doc_stats.items():
                    global_stats["replacements_by_type"][k] += v

            # Salva o arquivo anonimizado
            output_file = ANONYMIZED_DIR / f"{record_id}.json"
            with open(output_file, "w", encoding="utf-8") as f:
                json.dump(anon_data, f, ensure_ascii=False, indent=2)

            success += 1
            if index % 10 == 0 or index == len(json_files):
                logger.info(
                    f"[{index}/{len(json_files)}] Processado: {record_id} "
                    f"({doc_total_replacements} substituições)"
                )

        except Exception as err:
            errors += 1
            logger.error(f"Erro ao anonimizar {file_path.name}: {err}")

    # Salva relatório de estatísticas de anonimização
    stats_file = ANONYMIZED_DIR / "anonymization_stats.json"
    with open(stats_file, "w", encoding="utf-8") as f:
        json.dump(global_stats, f, ensure_ascii=False, indent=2)

    logger.info("=" * 60)
    logger.info("ANONIMIZAÇÃO CONCLUÍDA")
    logger.info(f"Sucesso: {success} | Erros: {errors}")
    logger.info(f"Documentos com PII anonimizada: {global_stats['anonymized_documents']}")
    logger.info(f"Total de itens anonimizados: {global_stats['total_replacements']}")
    logger.info(f"Relatório salvo em: {stats_file}")

    return success, errors


if __name__ == "__main__":
    max_limit = env_int("ANONYMIZE_MAX_FILES", 0)
    limit = max_limit if max_limit > 0 else None
    run(max_files=limit)
