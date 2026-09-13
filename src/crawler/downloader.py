"""
Orquestrador de download dos PDFs da BDTD.

Entrada:
    data/raw/metadata/records/*.json

Saída:
    data/raw/pdf/<record_id>.pdf

Manifestos:
    data/raw/manifests/download_manifest.json
    data/raw/manifests/failed_downloads.json

Responsabilidades:
- carregar os metadados;
- percorrer os registros;
- verificar PDFs existentes;
- chamar repository_parser;
- registrar sucessos e falhas.

A descoberta específica dos PDFs pertence ao
repository_parser.py.
"""

import json
import os
import re
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

from src.config import (
    MANIFEST_DIR,
    METADATA_DIR,
    PDF_DIR,
    create_directories,
)

from src.crawler.download_utils import (
    content_is_pdf_bytes,
)

from src.crawler.repository_parser import (
    process_repository_url,
)


# ============================================================
# CONFIGURAÇÕES
# ============================================================

MAX_RECORDS = int(
    os.getenv(
        "BDTD_MAX_RECORDS",
        "100",
    )
)

HEADLESS = (
    os.getenv(
        "BDTD_HEADLESS",
        "false",
    ).lower()
    == "true"
)


# ============================================================
# JSON
# ============================================================

def load_json(path: Path):
    """Lê um arquivo JSON."""

    with path.open(
        "r",
        encoding="utf-8",
    ) as file:
        return json.load(file)


def save_json(
    path: Path,
    data,
):
    """Salva dados em formato JSON."""

    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    with path.open(
        "w",
        encoding="utf-8",
    ) as file:
        json.dump(
            data,
            file,
            ensure_ascii=False,
            indent=2,
        )


def save_manifest(manifest):
    """
    Salva o manifesto incremental de downloads.

    É utilizado durante a execução para evitar perda
    das informações já processadas caso o crawler seja
    interrompido.
    """

    save_json(
        MANIFEST_DIR
        / "download_manifest.json",
        manifest,
    )


# ============================================================
# METADADOS
# ============================================================

def load_metadata_files():
    """
    Carrega os arquivos individuais de metadados,
    respeitando o limite BDTD_MAX_RECORDS.
    """

    return sorted(
        METADATA_DIR.glob("*.json")
    )[:MAX_RECORDS]


# ============================================================
# URLs
# ============================================================

def split_access_urls(value):
    """
    Extrai uma ou mais URLs do campo access_url.

    Mantém compatibilidade com metadados antigos
    que possam conter várias URLs no mesmo campo.
    """

    if not value:
        return []

    if isinstance(value, list):
        values = value

    else:
        values = (
            str(value)
            .splitlines()
        )

    urls = []

    for item in values:

        matches = re.findall(
            r"https?://[^\s]+",
            str(item),
        )

        for url in matches:

            url = url.strip()

            if url not in urls:
                urls.append(url)

    return urls


# ============================================================
# VALIDAÇÃO DE PDF EXISTENTE
# ============================================================

def is_valid_existing_pdf(
    path: Path,
) -> bool:
    """
    Verifica se um PDF já existente possui
    assinatura binária válida.

    O teste usa os primeiros bytes do arquivo,
    procurando pela assinatura padrão %PDF.

    Isso evita considerar como PDF válido uma
    página HTML salva incorretamente com extensão .pdf.
    """

    if not path.exists():
        return False

    if not path.is_file():
        return False

    try:

        # Um PDF precisa conter pelo menos alguns bytes.
        if path.stat().st_size < 5:
            return False

        # Não é necessário carregar o arquivo inteiro.
        with path.open("rb") as file:
            header = file.read(8)

        return content_is_pdf_bytes(
            header,
            "",
        )

    except Exception as error:

        print(
            "Erro ao validar PDF existente:",
            error,
        )

        return False


# ============================================================
# EXECUÇÃO
# ============================================================

def run():
    """
    Executa o downloader para os registros existentes em:

        data/raw/metadata/records/

    PDFs válidos já existentes não são baixados novamente.
    """

    create_directories()

    metadata_files = (
        load_metadata_files()
    )

    print(
        f"Metadados encontrados: "
        f"{len(metadata_files)}"
    )

    print(
        f"PDF_DIR: {PDF_DIR}"
    )

    print(
        f"HEADLESS: {HEADLESS}"
    )

    downloaded_now = 0
    already_exists = 0
    failed = 0

    manifest = []

    # ========================================================
    # PLAYWRIGHT
    # ========================================================

    with sync_playwright() as playwright:

        browser = (
            playwright.chromium.launch(
                headless=HEADLESS,
            )
        )

        context = (
            browser.new_context(
                ignore_https_errors=True,
            )
        )

        page = context.new_page()

        # ====================================================
        # REGISTROS
        # ====================================================

        for index, metadata_file in enumerate(
            metadata_files,
            start=1,
        ):

            metadata = load_json(
                metadata_file
            )

            record_id = (
                metadata.get("record_id")
                or metadata_file.stem
            )

            output_file = (
                PDF_DIR
                / f"{record_id}.pdf"
            )

            print()
            print("=" * 70)

            print(
                f"[{index}/"
                f"{len(metadata_files)}]"
            )

            print(
                f"Registro: {record_id}"
            )

            # ------------------------------------------------
            # PDF já existe
            # ------------------------------------------------

            if output_file.exists():

                if is_valid_existing_pdf(
                    output_file
                ):

                    print(
                        "PDF já existe e é válido."
                    )

                    already_exists += 1

                    manifest.append(
                        {
                            "record_id": record_id,
                            "status": (
                                "already_exists"
                            ),
                            "pdf_path": str(
                                output_file
                            ),
                        }
                    )

                    # Salva antes do continue.
                    save_manifest(
                        manifest
                    )

                    continue

                print(
                    "PDF existente inválido. "
                    "Será removido e baixado novamente."
                )

                try:

                    output_file.unlink()

                except Exception as error:

                    print(
                        "Não foi possível remover "
                        "o PDF inválido:",
                        error,
                    )

                    failed += 1

                    manifest.append(
                        {
                            "record_id": record_id,
                            "status": "failed",
                            "reason": (
                                "invalid_existing_pdf"
                            ),
                            "pdf_path": str(
                                output_file
                            ),
                        }
                    )

                    save_manifest(
                        manifest
                    )

                    continue

            # ------------------------------------------------
            # URLs de acesso
            # ------------------------------------------------

            access_urls = (
                split_access_urls(
                    metadata.get(
                        "access_url"
                    )
                )
            )

            if not access_urls:

                failed += 1

                manifest.append(
                    {
                        "record_id": record_id,
                        "status": (
                            "no_access_url"
                        ),
                        "reason": (
                            "no_access_url"
                        ),
                    }
                )

                print(
                    "Sem URL de acesso."
                )

                # Importante:
                # salva antes do continue.
                save_manifest(
                    manifest
                )

                continue

            success = False

            final_reason = (
                "unknown"
            )

            successful_url = None

            # ------------------------------------------------
            # Tenta cada URL disponível
            # ------------------------------------------------

            for access_url in access_urls:

                print()
                print(
                    "Tentando:"
                )

                print(
                    access_url
                )

                try:

                    result = (
                        process_repository_url(
                            page,
                            context,
                            access_url,
                            output_file,
                        )
                    )

                except Exception as error:

                    print(
                        "Erro ao processar "
                        "repositório:",
                        error,
                    )

                    result = {
                        "success": False,
                        "reason": (
                            "repository_error"
                        ),
                    }

                if result["success"]:

                    success = True

                    successful_url = (
                        result.get("url")
                        or access_url
                    )

                    break

                final_reason = (
                    result.get(
                        "reason",
                        "unknown",
                    )
                )

                print(
                    "Falhou:",
                    final_reason,
                )

                # Não tenta contornar mecanismos
                # explícitos de proteção ou restrição.
                if final_reason in {
                    "restricted_or_embargo",
                    "anti_bot",
                }:
                    break

            # ------------------------------------------------
            # SUCESSO
            # ------------------------------------------------

            if success:

                downloaded_now += 1

                manifest.append(
                    {
                        "record_id": record_id,
                        "status": (
                            "downloaded"
                        ),
                        "source_url": (
                            successful_url
                        ),
                        "pdf_path": str(
                            output_file
                        ),
                    }
                )

                print(
                    "PDF salvo:"
                )

                print(
                    output_file
                )

            # ------------------------------------------------
            # FALHA
            # ------------------------------------------------

            else:

                failed += 1

                manifest.append(
                    {
                        "record_id": record_id,
                        "status": "failed",
                        "access_urls": (
                            access_urls
                        ),
                        "reason": (
                            final_reason
                        ),
                    }
                )

            # ------------------------------------------------
            # Manifesto incremental
            # ------------------------------------------------

            save_manifest(
                manifest
            )

            # Pequeno intervalo para reduzir a frequência
            # de requisições aos repositórios externos.
            time.sleep(1)

        browser.close()

    # ========================================================
    # FALHAS
    # ========================================================

    failures = [
        item
        for item in manifest
        if item["status"]
        in {
            "failed",
            "no_access_url",
        }
    ]

    save_json(
        MANIFEST_DIR
        / "failed_downloads.json",
        failures,
    )

    # Garante que o manifesto final também esteja atualizado.
    save_manifest(
        manifest
    )

    total_pdfs = len(
        list(
            PDF_DIR.glob(
                "*.pdf"
            )
        )
    )

    # ========================================================
    # RESUMO
    # ========================================================

    print()
    print("=" * 70)

    print(
        "DOWNLOAD FINALIZADO"
    )

    print(
        f"Baixados agora: "
        f"{downloaded_now}"
    )

    print(
        f"Já existentes: "
        f"{already_exists}"
    )

    print(
        f"Falhas: "
        f"{failed}"
    )

    print(
        f"Total de PDFs: "
        f"{total_pdfs}"
    )

    print(
        "Manifesto:"
    )

    print(
        MANIFEST_DIR
        / "download_manifest.json"
    )

    print(
        "Falhas:"
    )

    print(
        MANIFEST_DIR
        / "failed_downloads.json"
    )


if __name__ == "__main__":
    run()