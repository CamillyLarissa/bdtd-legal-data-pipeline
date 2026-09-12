"""
Orquestrador de download dos PDFs da BDTD.

Entrada:
    data/raw/metadata/records/*.json

Saída:
    data/raw/pdf/<record_id>.pdf

Manifestos:
    data/raw/manifests/download_manifest.json
    data/raw/manifests/failed_downloads.json

Responsabilidades deste arquivo:
- carregar os metadados;
- percorrer os registros;
- verificar PDFs existentes;
- chamar repository_parser;
- registrar sucesso e falha.

A lógica específica de descoberta dos PDFs não fica aqui.
"""

import json
import os
import re
import time

from playwright.sync_api import (
    sync_playwright,
)

from src.config import (
    MANIFEST_DIR,
    METADATA_DIR,
    PDF_DIR,
    create_directories,
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


def load_json(path):
    """
    Lê um arquivo JSON.
    """

    with open(
        path,
        "r",
        encoding="utf-8",
    ) as file:

        return json.load(file)


def save_json(
    path,
    data,
):
    """
    Salva um arquivo JSON.
    """

    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    with open(
        path,
        "w",
        encoding="utf-8",
    ) as file:

        json.dump(
            data,
            file,
            ensure_ascii=False,
            indent=2,
        )


def load_metadata_files():
    """
    Carrega os arquivos individuais de metadata,
    respeitando BDTD_MAX_RECORDS.
    """

    return sorted(
        METADATA_DIR.glob(
            "*.json"
        )
    )[:MAX_RECORDS]


# ============================================================
# URLs
# ============================================================


def split_access_urls(value):
    """
    Extrai uma ou mais URLs do campo access_url.

    Mantém compatibilidade com metadados antigos
    que podiam conter múltiplas URLs no mesmo campo.
    """

    if not value:
        return []

    if isinstance(
        value,
        list,
    ):
        values = value

    else:
        values = (
            str(value)
            .splitlines()
        )

    urls = []

    for value in values:

        matches = re.findall(
            r"https?://[^\s]+",
            str(value),
        )

        for url in matches:

            url = url.strip()

            if url not in urls:
                urls.append(url)

    return urls


# ============================================================
# EXECUÇÃO
# ============================================================


def run():
    """
    Executa o downloader para os registros encontrados
    em data/raw/metadata/records.
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

    with sync_playwright() as p:

        browser = (
            p.chromium.launch(
                headless=HEADLESS
            )
        )

        context = (
            browser.new_context(
                ignore_https_errors=True
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
                metadata.get(
                    "record_id"
                )
                or metadata_file.stem
            )

            output_file = (
                PDF_DIR
                / f"{record_id}.pdf"
            )

            print(
                "\n"
                + "=" * 70
            )

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

                print(
                    "PDF já existe."
                )

                already_exists += 1

                manifest.append(
                    {
                        "record_id": (
                            record_id
                        ),
                        "status": (
                            "already_exists"
                        ),
                        "pdf_path": str(
                            output_file
                        ),
                    }
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
                        "record_id": (
                            record_id
                        ),
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

                print(
                    "\nTentando:"
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
                        access_url
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

                # Não há motivo para tentar contornar
                # uma restrição explícita.
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
                        "record_id": (
                            record_id
                        ),
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
                        "record_id": (
                            record_id
                        ),
                        "status": (
                            "failed"
                        ),
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

            save_json(
                MANIFEST_DIR
                / "download_manifest.json",
                manifest,
            )

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

    print(
        "\n"
        + "=" * 70
    )

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
        f"Falhas: {failed}"
    )

    print(
        f"Total de PDFs: "
        f"{total_pdfs}"
    )


if __name__ == "__main__":
    run()