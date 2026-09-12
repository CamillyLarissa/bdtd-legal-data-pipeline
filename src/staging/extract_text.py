"""
Módulo de extração de texto da camada Staging.

Converte documentos PDF (da pasta data/raw/pdf, Google Drive ou data/samples/pdf)
em arquivos JSON estruturados por página armazenados na camada Staging.
"""

import json
import logging
from pathlib import Path
import sys
import fitz  # PyMuPDF

from src.config import DATA_DIR, PDF_DIR, STAGING_DIR, env_int

# Configuração de logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)


def get_pdf_sources() -> tuple[list[Path], Path]:
    """
    Retorna uma tupla (lista_de_pdfs, diretorio_de_saida_staging).

    Ordem de busca:
    1. PDF_DIR (definido via BDTD_DATA_DIR ou padrão data/raw/pdf)
    2. Caminhos comuns do Google Drive no Colab (ex: /content/drive/MyDrive/bdtd-legal-data/data/raw/pdf)
    3. Amostras locais em data/samples/pdf
    """
    # 1. Verifica PDF_DIR configurado
    if PDF_DIR.exists():
        pdf_files = sorted(list(PDF_DIR.glob("*.pdf")))
        if pdf_files:
            logger.info(f"PDFs encontrados em {PDF_DIR}: {len(pdf_files)}")
            return pdf_files, STAGING_DIR

    # 2. Verifica caminhos comuns do Google Drive no Colab
    colab_drive_paths = [
        Path("/content/drive/MyDrive/bdtd-legal-data/data/raw/pdf"),
        Path("/content/drive/MyDrive/bdtd-legal/data/raw/pdf"),
        Path("/content/drive/Shareddrives/bdtd-legal-data/data/raw/pdf"),
    ]
    for drive_path in colab_drive_paths:
        if drive_path.exists():
            pdf_files = sorted(list(drive_path.glob("*.pdf")))
            if pdf_files:
                target_staging = drive_path.parent.parent / "staging"
                logger.info(
                    f"PDFs encontrados no Google Drive ({drive_path}): {len(pdf_files)}. "
                    f"Saída Staging em: {target_staging}"
                )
                return pdf_files, target_staging

    # 3. Fallback para pasta de amostras locais
    sample_dir = DATA_DIR / "samples" / "pdf"
    if sample_dir.exists():
        pdf_files = sorted(list(sample_dir.glob("*.pdf")))
        if pdf_files:
            logger.info(
                f"Nenhum PDF em {PDF_DIR} ou Google Drive. Usando {len(pdf_files)} PDFs de amostra em {sample_dir}."
            )
            return pdf_files, STAGING_DIR

    return [], STAGING_DIR


def get_pdf_files() -> list[Path]:
    """
    Retorna a lista de PDFs a serem processados (alias para compatibilidade).
    """
    files, _ = get_pdf_sources()
    return files


def extract_text_from_pdf(pdf_path: Path) -> dict:
    """
    Extrai texto página por página de um PDF usando PyMuPDF (fitz).

    Retorna um dicionário contendo:
      - total_pages: número total de páginas
      - pages: lista de dicionários {"page": num, "text": conteúdo}
    """
    document = fitz.open(pdf_path)
    total_pages = len(document)
    pages = []

    for page_number, page in enumerate(document, start=1):
        text = page.get_text("text")
        pages.append({
            "page": page_number,
            "text": text,
        })

    document.close()

    return {
        "total_pages": total_pages,
        "pages": pages,
    }


def save_staging(record_id: str, data: dict, output_dir: Path | None = None) -> Path:
    """
    Salva o dicionário extraído em formato JSON na pasta de Staging.
    """
    target_dir = output_dir or STAGING_DIR
    target_dir.mkdir(parents=True, exist_ok=True)
    output_file = target_dir / f"{record_id}.json"

    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    return output_file


def run(max_files: int | None = None) -> tuple[int, int]:
    """
    Executa a extração de Staging para todos os PDFs encontrados.
    """
    pdf_files, target_staging_dir = get_pdf_sources()

    if not pdf_files:
        logger.warning("Nenhum arquivo PDF encontrado em data/raw/pdf, Google Drive ou data/samples/pdf.")
        return 0, 0

    if max_files and max_files > 0:
        pdf_files = pdf_files[:max_files]

    logger.info(f"Iniciando extração de Staging para {len(pdf_files)} arquivos PDF...")

    success = 0
    errors = 0

    for index, pdf_path in enumerate(pdf_files, start=1):
        record_id = pdf_path.stem

        print("\n" + "=" * 60)
        logger.info(f"[{index}/{len(pdf_files)}] Processando {record_id}")

        try:
            extracted = extract_text_from_pdf(pdf_path)

            staging_data = {
                "record_id": record_id,
                "source_pdf": str(pdf_path),
                "total_pages": extracted["total_pages"],
                "pages": extracted["pages"],
            }

            output_file = save_staging(record_id, staging_data, output_dir=target_staging_dir)
            success += 1

            total_chars = sum(len(p["text"]) for p in extracted["pages"])
            logger.info(
                f"Páginas: {extracted['total_pages']} | Caracteres: {total_chars} | Salvo em: {output_file}"
            )

        except Exception as error:
            errors += 1
            logger.error(f"Erro ao extrair texto de {pdf_path.name}: {error}")

    print("\n" + "=" * 60)
    logger.info("STAGING FINALIZADO")
    logger.info(f"Sucesso: {success}")
    logger.info(f"Erros: {errors}")

    return success, errors


if __name__ == "__main__":
    max_limit = env_int("STAGING_MAX_FILES", 0)
    limit = max_limit if max_limit > 0 else None
    run(max_files=limit)
