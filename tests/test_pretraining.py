"""
Testes unitários para a camada Curated de Pré-Treino Continuado (src/curated/pretraining.py).
"""

import json
from pathlib import Path
import pytest

from src.curated.pretraining import (
    extract_full_text_from_doc,
    run,
    END_OF_DOC_TOKEN,
)


def test_extract_full_text_from_doc():
    doc = {
        "record_id": "TEST_PRETRAIN",
        "pages": [
            {"page": 1, "text": "Página um sobre direito constitucional."},
            {"page": 2, "text": "Página dois sobre direitos fundamentais."}
        ]
    }

    full_text, pages_count = extract_full_text_from_doc(doc)

    assert pages_count == 2
    assert "Página um" in full_text
    assert "Página dois" in full_text
    assert "\n\n" in full_text


def test_pretraining_run(tmp_path: Path, monkeypatch):
    """
    Testa a geração dos arquivos de pré-treino continuado (.jsonl, .txt, _summary.json).
    """
    # Criar pasta de entrada temporária simulando anonymized
    input_dir = tmp_path / "anonymized"
    input_dir.mkdir(parents=True)

    doc_data = {
        "record_id": "DOC_001",
        "source_pdf": "data/raw/pdf/DOC_001.pdf",
        "pages": [
            {"page": 1, "text": "Texto para treino da LLM em direito."}
        ]
    }
    with open(input_dir / "DOC_001.json", "w", encoding="utf-8") as f:
        json.dump(doc_data, f)

    # Monkeypatch para direcionar diretórios de teste
    import src.curated.pretraining as pret
    monkeypatch.setattr(pret, "ANONYMIZED_DIR", input_dir)
    monkeypatch.setattr(pret, "PRETRAINING_DIR", tmp_path / "pretraining_output")

    success, errors = pret.run()

    assert success == 1
    assert errors == 0

    output_dir = tmp_path / "pretraining_output"
    jsonl_file = output_dir / "pretraining_corpus.jsonl"
    txt_file = output_dir / "pretraining_corpus.txt"
    summary_file = output_dir / "pretraining_summary.json"

    assert jsonl_file.exists()
    assert txt_file.exists()
    assert summary_file.exists()

    # Validar conteúdo do TXT (presença de <|endoftext|>)
    txt_content = txt_file.read_text(encoding="utf-8")
    assert END_OF_DOC_TOKEN in txt_content
    assert "Texto para treino da LLM em direito." in txt_content

    # Validar JSONL
    jsonl_line = json.loads(jsonl_file.read_text(encoding="utf-8").strip())
    assert jsonl_line["id"] == "DOC_001"
    assert jsonl_line["metadata"]["word_count"] > 0
