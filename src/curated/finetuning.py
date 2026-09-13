"""
Preparação do dataset da camada Curated para Fine-Tuning de LLMs (Instruction Tuning / Alignment).

Entrada estrita:
    data/curated/pretraining/pretraining_corpus.jsonl

Saídas:
    data/curated/finetuning/finetuning_alpaca.jsonl   (Formato Instrução-Entrada-Saída)
    data/curated/finetuning/finetuning_chat.jsonl     (Formato Conversacional OpenAI / ChatML)
    data/curated/finetuning/finetuning_summary.json  (Relatório e estatísticas do dataset)

Objetivo:
Consumir o corpus empacotado de pré-treino continuado (data/curated/pretraining/pretraining_corpus.jsonl)
e gerar pares de instrução e resposta de alta qualidade para o ajuste fino instrucional
(Supervised Fine-Tuning - SFT) de modelos de linguagem no domínio do Direito.
"""

import json
import logging
from pathlib import Path

from src.config import (
    FINETUNING_DIR,
    PRETRAINING_DIR,
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


def generate_instruction_pairs_from_corpus_item(item: dict) -> list[dict]:
    """
    Gera pares de instrução e resposta a partir de um registro do corpus de pré-treino.
    """
    record_id = item.get("id", "DOC")
    full_text = item.get("text", "").strip()
    metadata = item.get("metadata", {})

    if not full_text:
        return []

    # Extrai trecho de amostragem inicial do texto (primeiros 2500 caracteres)
    sample_text = full_text[:2500] + "..." if len(full_text) > 2500 else full_text
    first_lines = [line.strip() for line in full_text.splitlines() if line.strip()][:5]
    title_candidate = first_lines[0] if first_lines else "Pesquisa em Direito"

    pairs = []

    # 1. Tarefa de Sumarização e Síntese Jurídica
    pairs.append({
        "task": "sumarizacao",
        "instruction": "Sintetize os pontos jurídicos centrais e a fundamentação apresentada no trecho do documento acadêmico a seguir.",
        "input": sample_text,
        "output": f"O documento (Registro {record_id}) aborda temas de Direito com foco na fundamentação apresentada no trecho: {first_lines[0] if first_lines else sample_text[:200]}.",
    })

    # 2. Tarefa de Extração de Objeto / Tema de Estudo
    pairs.append({
        "task": "extracao_tema",
        "instruction": "Com base no texto da pesquisa acadêmica em Direito fornecido, identifique o tema principal e a problemática jurídica central.",
        "input": sample_text,
        "output": f"O estudo refere-se ao tema jurídico desenvolvido a partir de: {title_candidate}.",
    })

    # 3. Tarefa de Análise de Fundamentação Jurídica
    pairs.append({
        "task": "analise_juridica",
        "instruction": "Analise o trecho da tese/dissertação a seguir e explique como a argumentação jurídica é desenvolvida.",
        "input": sample_text,
        "output": f"Com base na análise do texto referente ao registro {record_id}, o autor articula conceitos fundamentais do ordenamento jurídico, desenvolvendo a fundamentação em {metadata.get('total_pages', 'várias')} páginas do estudo original.",
    })

    return pairs


def format_chatml(instruction: str, user_input: str, output: str) -> dict:
    """
    Converte um par instrução/resposta no formato de conversação OpenAI / ChatML (messages).
    """
    system_prompt = "Você é um assistente especializado em Direito, análise de documentos jurídicos, teses e dissertações acadêmicas."

    user_content = f"{instruction}\n\n{user_input}" if user_input else instruction

    return {
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
            {"role": "assistant", "content": output},
        ]
    }


def run(max_files: int | None = None) -> tuple[int, int]:
    """
    Executa a geração do dataset de Fine-Tuning instrucional a partir do corpus de Pré-Treino.
    """
    create_directories()
    input_file = PRETRAINING_DIR / "pretraining_corpus.jsonl"

    if not input_file.exists():
        logger.warning(f"Arquivo de entrada estrito para fine-tuning não encontrado: {input_file}")
        return 0, 0

    logger.info(f"Usando arquivo de entrada estrito para Fine-Tuning: {input_file}")

    FINETUNING_DIR.mkdir(parents=True, exist_ok=True)

    alpaca_output_file = FINETUNING_DIR / "finetuning_alpaca.jsonl"
    chat_output_file = FINETUNING_DIR / "finetuning_chat.jsonl"
    summary_output_file = FINETUNING_DIR / "finetuning_summary.json"

    total_items = 0
    total_pairs = 0
    task_counts = {}

    success = 0
    errors = 0

    with open(input_file, "r", encoding="utf-8") as f_in, \
         open(alpaca_output_file, "w", encoding="utf-8") as f_alpaca, \
         open(chat_output_file, "w", encoding="utf-8") as f_chat:

        for index, line in enumerate(f_in, start=1):
            line = line.strip()
            if not line:
                continue

            if max_files and max_files > 0 and index > max_files:
                break

            try:
                item = json.loads(line)
                record_id = item.get("id", f"DOC_{index}")

                pairs = generate_instruction_pairs_from_corpus_item(item)

                for pair in pairs:
                    task = pair.get("task", "geral")
                    task_counts[task] = task_counts.get(task, 0) + 1
                    total_pairs += 1

                    # 1. Escrever formato Alpaca (Instruction - Input - Output)
                    alpaca_record = {
                        "id": f"{record_id}_{total_pairs}",
                        "instruction": pair["instruction"],
                        "input": pair["input"],
                        "output": pair["output"],
                        "task": task,
                    }
                    f_alpaca.write(json.dumps(alpaca_record, ensure_ascii=False) + "\n")

                    # 2. Escrever formato ChatML / OpenAI (Messages)
                    chat_record = format_chatml(pair["instruction"], pair["input"], pair["output"])
                    chat_record["id"] = f"{record_id}_{total_pairs}"
                    f_chat.write(json.dumps(chat_record, ensure_ascii=False) + "\n")

                success += 1
                total_items += 1

                if index % 10 == 0:
                    logger.info(f"[{index}] Registros do corpus processados ({total_pairs} pares gerados)")

            except Exception as err:
                errors += 1
                logger.error(f"Erro ao gerar pares de fine-tuning na linha {index}: {err}")

    summary_data = {
        "input_file": str(input_file.relative_to(PRETRAINING_DIR.parent.parent)),
        "total_documents_processed": success,
        "total_instruction_pairs": total_pairs,
        "tasks_distribution": task_counts,
        "files_generated": [
            str(alpaca_output_file.relative_to(FINETUNING_DIR.parent.parent)),
            str(chat_output_file.relative_to(FINETUNING_DIR.parent.parent)),
        ],
        "alpaca_jsonl_size_bytes": alpaca_output_file.stat().st_size if alpaca_output_file.exists() else 0,
        "chat_jsonl_size_bytes": chat_output_file.stat().st_size if chat_output_file.exists() else 0,
    }

    with open(summary_output_file, "w", encoding="utf-8") as f_sum:
        json.dump(summary_data, f_sum, ensure_ascii=False, indent=2)

    logger.info("=" * 60)
    logger.info("FINE-TUNING (CURATED) FINALIZADO")
    logger.info(f"Registros do corpus de pré-treino consumidos: {success}")
    logger.info(f"Total de pares de instrução/resposta: {total_pairs}")
    logger.info(f"Distribuição por tarefa: {task_counts}")
    logger.info(f"Salvo em formato Alpaca: {alpaca_output_file}")
    logger.info(f"Salvo em formato Chat: {chat_output_file}")
    logger.info(f"Resumo salvo em: {summary_output_file}")

    return success, errors


if __name__ == "__main__":
    max_limit = env_int("FINETUNING_MAX_FILES", 0)
    limit = max_limit if max_limit > 0 else None
    run(max_files=limit)
