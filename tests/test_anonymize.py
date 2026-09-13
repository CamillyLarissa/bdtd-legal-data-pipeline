"""
Testes unitários para o módulo de anonimização (src/processed/anonymize.py).
"""

from pathlib import Path
import json
import pytest

from src.processed.anonymize import (
    anonymize_text,
    anonymize_document,
    run,
)


def test_anonymize_text_cpf():
    text = "O requerente com CPF 123.456.789-00 solicitou o documento."
    anon_text, stats = anonymize_text(text)
    assert "[CPF_ANONIMIZADO]" in anon_text
    assert "123.456.789-00" not in anon_text
    assert stats["cpf"] == 1


def test_anonymize_text_cnpj():
    text = "Empresa X com CNPJ 12.345.678/0001-90 contratada."
    anon_text, stats = anonymize_text(text)
    assert "[CNPJ_ANONIMIZADO]" in anon_text
    assert "12.345.678/0001-90" not in anon_text
    assert stats["cnpj"] == 1


def test_anonymize_text_email():
    text = "Contato do advogado: joao.silva@advocacia.com.br para informações."
    anon_text, stats = anonymize_text(text)
    assert "[EMAIL_ANONIMIZADO]" in anon_text
    assert "joao.silva@advocacia.com.br" not in anon_text
    assert stats["email"] == 1


def test_anonymize_text_processo_cnj():
    text = "Ref. ao Processo nº 1234567-89.2023.8.26.0100 em andamento."
    anon_text, stats = anonymize_text(text)
    assert "[PROCESSO_ANONIMIZADO]" in anon_text
    assert "1234567-89.2023.8.26.0100" not in anon_text
    assert stats["processo_cnj"] == 1


def test_anonymize_text_oab():
    text = "Dr. Fulano registrado sob a OAB/SP 123456."
    anon_text, stats = anonymize_text(text)
    assert "[OAB_ANONIMIZADO]" in anon_text
    assert "OAB/SP 123456" not in anon_text
    assert stats["oab"] == 1


def test_anonymize_text_rg_cep_endereco():
    text = "Portador do RG nº 12.345.678-9, morador da Avenida Paulista, nº 1000, CEP 01310-100."
    anon_text, stats = anonymize_text(text)
    assert "[RG_ANONIMIZADO]" in anon_text
    assert "[ENDERECO_ANONIMIZADO]" in anon_text
    assert "[CEP_ANONIMIZADO]" in anon_text
    assert stats["rg"] == 1
    assert stats["endereco"] == 1
    assert stats["cep"] == 1


def test_anonymize_document(tmp_path: Path):
    doc = {
        "record_id": "TEST_001",
        "title": "Tese sobre CPF 111.222.333-44",
        "pages": [
            {"page": 1, "text": "Contato: email@teste.com ou telefone 11 98765-4321"}
        ]
    }

    anon_doc, stats = anonymize_document(doc)

    assert "[CPF_ANONIMIZADO]" in anon_doc["title"]
    assert "[EMAIL_ANONIMIZADO]" in anon_doc["pages"][0]["text"]
    assert stats["cpf"] == 1
    assert stats["email"] == 1
    assert stats["telefone"] == 1
