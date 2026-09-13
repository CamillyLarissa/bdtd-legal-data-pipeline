"""
Testes unitários para o módulo de Fine-Tuning (src/curated/finetuning.py).
"""

import json
from pathlib import Path
import pytest

from src.curated.finetuning import (
    generate_instruction_pairs_from_corpus_item,
    format_chatml,
    run,
)


def test_generate_instruction_pairs_from_corpus_item():
    item = {
        "id": "TEST_PRETRAIN_001",
        "text": "Direito Ambiental e Sustentabilidade.\n\nTexto completo da tese sobre preservação ambiental no Brasil.",
        "metadata": {
            "source_pdf": "data/raw/pdf/TEST_PRETRAIN_001.pdf",
            "total_pages": 50,
            "word_count": 200,
            "char_count": 1200,
        }
    }

    pairs = generate_instruction_pairs_from_corpus_item(item)

    assert len(pairs) >= 2
    tasks = [p["task"] for p in pairs]
    assert "sumarizacao" in tasks
    assert "extracao_tema" in tasks


def test_format_chatml():
    instruction = "Resuma o texto."
    user_input = "Texto do documento."
    output = "Resumo do documento."

    chatml = format_chatml(instruction, user_input, output)

    assert "messages" in chatml
    assert len(chatml["messages"]) == 3
    assert chatml["messages"][0]["role"] == "system"
    assert chatml["messages"][1]["role"] == "user"
    assert chatml["messages"][2]["role"] == "assistant"
    assert output in chatml["messages"][2]["content"]


def test_finetuning_run(tmp_path: Path, monkeypatch):
    pretraining_dir = tmp_path / "pretraining"
    pretraining_dir.mkdir(parents=True)

    input_jsonl = pretraining_dir / "pretraining_corpus.jsonl"
    corpus_record = {
        "id": "DOC_CPT_001",
        "text": "Texto consolidado de pré-treino continuado em direito civil.",
        "metadata": {"total_pages": 10, "word_count": 100, "char_count": 600}
    }
    with open(input_jsonl, "w", encoding="utf-8") as f:
        f.write(json.dumps(corpus_record, ensure_ascii=False) + "\n")

    import src.curated.finetuning as ft
    monkeypatch.setattr(ft, "PRETRAINING_DIR", pretraining_dir)
    monkeypatch.setattr(ft, "FINETUNING_DIR", tmp_path / "finetuning_output")

    success, errors = ft.run()

    assert success == 1
    assert errors == 0

    output_dir = tmp_path / "finetuning_output"
    alpaca_file = output_dir / "finetuning_alpaca.jsonl"
    chat_file = output_dir / "finetuning_chat.jsonl"
    summary_file = output_dir / "finetuning_summary.json"

    assert alpaca_file.exists()
    assert chat_file.exists()
    assert summary_file.exists()
