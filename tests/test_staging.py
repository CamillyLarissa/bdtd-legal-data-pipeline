"""
Testes unitários e de integração para o módulo de Staging (src/staging/extract_text.py).
"""

import json
from pathlib import Path
import pytest
import fitz

from src.staging.extract_text import (
    extract_text_from_pdf,
    save_staging,
    get_pdf_files,
    run,
)


@pytest.fixture
def sample_pdf(tmp_path: Path) -> Path:
    """
    Cria um PDF fictício simples para testes usando PyMuPDF.
    """
    pdf_path = tmp_path / "TEST_doc123.pdf"
    doc = fitz.open()
    
    page1 = doc.new_page()
    page1.insert_text((50, 50), "Texto de teste na página 1 - Direitos Fundamentais.")
    
    page2 = doc.new_page()
    page2.insert_text((50, 50), "Texto de teste na página 2 - Biblioteca Digital BDTD.")
    
    doc.save(pdf_path)
    doc.close()
    return pdf_path


def test_extract_text_from_pdf(sample_pdf: Path):
    """
    Verifica se a extração retorna o número correto de páginas e o texto de cada página.
    """
    result = extract_text_from_pdf(sample_pdf)

    assert result["total_pages"] == 2
    assert len(result["pages"]) == 2
    assert result["pages"][0]["page"] == 1
    assert "Direitos Fundamentais" in result["pages"][0]["text"]
    assert result["pages"][1]["page"] == 2
    assert "Biblioteca Digital BDTD" in result["pages"][1]["text"]


def test_save_staging(tmp_path: Path):
    """
    Verifica a gravação do arquivo JSON no diretório de Staging.
    """
    record_id = "TEST_doc123"
    data = {
        "record_id": record_id,
        "source_pdf": "data/raw/pdf/TEST_doc123.pdf",
        "total_pages": 1,
        "pages": [{"page": 1, "text": "Exemplo de conteúdo"}],
    }

    output_file = save_staging(record_id, data, output_dir=tmp_path)

    assert output_file.exists()
    assert output_file.name == "TEST_doc123.json"

    with open(output_file, "r", encoding="utf-8") as f:
        loaded = json.load(f)

    assert loaded["record_id"] == record_id
    assert loaded["total_pages"] == 1
    assert loaded["pages"][0]["text"] == "Exemplo de conteúdo"


def test_get_pdf_files_fallback():
    """
    Verifica se get_pdf_files() encontra PDFs ou cai para a pasta de amostras.
    """
    files = get_pdf_files()
    assert isinstance(files, list)
    # Deve retornar a lista de PDFs existentes (ex: da pasta data/samples/pdf ou data/raw/pdf)
    assert len(files) > 0
