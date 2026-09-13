"""
Anonimização de dados sensíveis e pessoais (PII) nos documentos da BDTD.

Entrada estrita:
    data/processed/03_deduplicated/*.json

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

REGEX_PROCESSO_CNJ = re.compile(r"\b\d{7}-\d{2}\.\d{4}\.\d\.\d{2}\.\d{4}\b")
REGEX_CPF = re.compile(r"\b\d{3}\.\d{3}\.\d{3}-\d{2}\b")
REGEX_CNPJ = re.compile(r"\b\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}\b")
REGEX_EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
REGEX_TELEFONE = re.compile(r"(?:\+?55\s?)?(?:\(?\d{2}\)?\s?)(?:9?\d{4}[-.\s]?\d{4})\b")
REGEX_OAB = re.compile(r"\bOAB(?:/[A-Z]{2}|-[A-Z]{2}|\s+[A-Z]{2})\s?\d{3,6}\b", re.IGNORECASE)
REGEX_RG = re.compile(r"\b(?:RG|R\.G\.)\s*(?:nº|nº\.|num|número)?\s*[\d\.\-]{5,14}\b", re.IGNORECASE)
REGEX_CEP = re.compile(r"\b\d{5}-\d{3}\b")
REGEX_ENDERECO = re.compile(r"\b(?:Rua|Av\.|Avenida|Alameda|Praça|Servidão)\s+[A-ZÀ-Úa-zà-ú0-9\s]{3,35},\s*nº?\s*\d+\b", re.IGNORECASE)
REGEX_DATA_NASC = re.compile(r"\b(?:nascido\(a\)|nascido em|data de nascimento:?)\s*\d{2}/\d{2}/\d{4}\b", re.IGNORECASE)


def anonymize_text(text: str, use_ner: bool = False) -> tuple[str, dict[str, int]]:
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

    if use_ner and SPACY_NLP is not None:
        try:
            doc = SPACY_NLP(text[:50000])
            per_entities = [ent.text for ent in doc.ents if ent.label_ == "PER" and len(ent.text) > 3]
            for name in set(per_entities):
                if " " in name:
                    text = text.replace(name, "[PESSOA_ANONIMIZADA]")
                    stats["ner_pessoas"] += 1
        except Exception as e:
            logger.debug(f"Erro na execução do NER spaCy: {e}")

    return text, stats


def anonymize_document(data: dict, use_ner: bool = False) -> tuple[dict, dict[str, int]]:
    total_stats = {
        "cpf": 0, "cnpj": 0, "email": 0, "telefone": 0,
        "processo_cnj": 0, "oab": 0, "rg": 0, "cep": 0,
        "endereco": 0, "data_nascimento": 0, "ner_pessoas": 0,
    }

    anonymized_data = json.loads(json.dumps(data))

    target_container = anonymized_data
    if "document" in anonymized_data and isinstance(anonymized_data["document"], dict) and "pages" in anonymized_data["document"]:
        target_container = anonymized_data["document"]

    if "pages" in target_container and isinstance(target_container["pages"], list):
        new_pages = []
        for page_info in target_container["pages"]:
            if isinstance(page_info, dict) and "text" in page_info and page_info["text"]:
                text_anon, page_stats = anonymize_text(page_info["text"], use_ner=use_ner)
                for k, v in page_stats.items():
                    total_stats[k] += v
                new_page = page_info.copy()
                new_page["text"] = text_anon
                new_pages.append(new_page)
            else:
                new_pages.append(page_info)
        target_container["pages"] = new_pages

    metadata_containers = [anonymized_data]
    if "metadata" in anonymized_data and isinstance(anonymized_data["metadata"], dict):
        metadata_containers.append(anonymized_data["metadata"])

    for container in metadata_containers:
        for field in ["resumo", "abstract", "title", "titulo"]:
            if field in container and isinstance(container[field], str) and container[field]:
                anon_val, field_stats = anonymize_text(container[field], use_ner=use_ner)
                for k, v in field_stats.items():
                    total_stats[k] += v
                container[field] = anon_val

    return anonymized_data, total_stats


def run(max_files: int | None = None, use_ner: bool | None = None) -> tuple[int, int]:
    create_directories()
    input_dir = DEDUPLICATED_DIR

    if use_ner is None:
        use_ner = env_bool("ANONYMIZE_USE_NER", False)

    if use_ner and SPACY_NLP is None:
        logger.info("ANONYMIZE_USE_NER=true, mas spaCy/modelo pt_core_news não instalado. Executando Nível 1 (Regex).")
        use_ner = False
    elif use_ner:
        logger.info("Anonimização Nível 2 (NER com spaCy) ATIVADA.")

    if not input_dir.exists():
        logger.warning(f"Diretório de entrada estrito {input_dir} não existe.")
        return 0, 0

    json_files = sorted([f for f in input_dir.glob("*.json") if f.name != "duplicates.json"])

    if not json_files:
        logger.warning(f"Nenhum arquivo JSON encontrado em {input_dir} (03_deduplicated).")
        return 0, 0

    if max_files and max_files > 0:
        json_files = json_files[:max_files]

    logger.info(f"Usando pasta de entrada estrita: {input_dir} ({len(json_files)} arquivos)")
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
            "cpf": 0, "cnpj": 0, "email": 0, "telefone": 0,
            "processo_cnj": 0, "oab": 0, "rg": 0, "cep": 0,
            "endereco": 0, "data_nascimento": 0, "ner_pessoas": 0,
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
