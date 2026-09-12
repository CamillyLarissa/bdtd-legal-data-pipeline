"""
Orquestrador do download de PDFs.

Fluxo:

metadados Raw
    ↓
access_url
    ↓
repository_parser
    ↓
PDF
    ↓
manifest

Este módulo não tenta interpretar internamente cada tipo de
repositório. Essa responsabilidade pertence a repository_parser.py.
"""

import json
from pathlib import Path

import requests
from playwright.sync_api import sync_playwright

from src.config import (
    BDTD_HEADLESS,
    MANIFEST_DIR,
    METADATA_DIR,
    PAGE_TIMEOUT,
    PDF_DIR,
    create_directories,
)

from src.crawler.repository_parser import (
    process_repository_url,
)


DOWNLOAD_MANIFEST_FILE = (
    MANIFEST_DIR
    / "download_manifest.json"
)

FAILED_DOWNLOADS_FILE = (
    MANIFEST_DIR
    / "failed_downloads.json"
)


def load_json(
    path: Path,
) -> dict:
    """
    Carrega um JSON.
    """
    with open(
        path,
        "r",
        encoding="utf-8",
    ) as file:
        return json.load(file)


def save_json(
    path: Path,
    data,
) -> None:
    """
    Salva JSON diretamente no arquivo final.

    Essa versão simples evita o problema anterior em que o
    código tentava ler um arquivo .tmp.
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


def split_access_urls(
    value,
) -> list[str]:
    """
    Converte o campo access_url em lista.

    Suporta:
    - uma única URL;
    - várias URLs separadas por quebra de linha;
    - lista de URLs.
    """
    if not value:
        return []

    if isinstance(
        value,
        list,
    ):
        values = value

    else:
        values = re_split_urls(
            str(value)
        )

    result_urls = []
    seen = set()

    for url in values:
        url = url.strip()

        if not url:
            continue

        if not url.startswith(
            ("http://", "https://")
        ):
            continue

        if url in seen:
            continue

        seen.add(url)
        result_urls.append(url)

    return result_urls


def re_split_urls(
    value: str,
) -> list[str]:
    """
    Separa múltiplas URLs que possam estar armazenadas
    em linhas diferentes.
    """
    values = []

    for line in value.splitlines():
        line = line.strip()

        if line:
            values.append(line)

    return values


def metadata_files() -> list[Path]:
    """
    Retorna todos os arquivos de metadados.
    """
    return sorted(
        METADATA_DIR.glob(
            "*.json"
        )
    )


def run() -> None:
    """
    Executa o downloader para todos os metadados disponíveis.
    """
    create_directories()

    files = metadata_files()

    print(
        f"Metadados encontrados: "
        f"{len(files)}"
    )

    manifest = []
    failures = []

    downloaded_now = 0
    already_existing = 0

    session = requests.Session()

    with sync_playwright() as playwright:
        browser = (
            playwright.chromium.launch(
                headless=BDTD_HEADLESS,
            )
        )

        page = browser.new_page()

        page.set_default_timeout(
            PAGE_TIMEOUT
        )

        for index, file_path in enumerate(
            files,
            start=1,
        ):
            try:
                metadata = load_json(
                    file_path
                )

            except Exception as error:
                print(
                    f"Erro ao ler "
                    f"{file_path.name}: "
                    f"{error}"
                )

                continue

            record_id = (
                metadata.get(
                    "record_id"
                )
                or file_path.stem
            )

            pdf_path = (
                PDF_DIR
                / f"{record_id}.pdf"
            )

            print(
                "\n"
                + "=" * 60
            )

            print(
                f"[{index}/{len(files)}] "
                f"{record_id}"
            )

            # ------------------------------------------------
            # Documento já baixado.
            # ------------------------------------------------

            if pdf_path.exists():
                already_existing += 1

                entry = {
                    "record_id": record_id,
                    "status": "already_exists",
                    "reason": None,
                    "source_url": None,
                    "pdf_url": None,
                    "pdf_path": str(
                        pdf_path
                    ),
                }

                manifest.append(entry)

                save_json(
                    DOWNLOAD_MANIFEST_FILE,
                    manifest,
                )

                print(
                    "PDF já existe."
                )

                continue

            access_urls = (
                split_access_urls(
                    metadata.get(
                        "access_url"
                    )
                )
            )

            if not access_urls:
                entry = {
                    "record_id": record_id,
                    "status": "failed",
                    "reason": "no_access_url",
                    "source_url": None,
                    "pdf_url": None,
                    "pdf_path": None,
                }

                manifest.append(entry)
                failures.append(entry)

                save_json(
                    DOWNLOAD_MANIFEST_FILE,
                    manifest,
                )

                print(
                    "Nenhuma URL de acesso."
                )

                continue

            final_result = None

            # ------------------------------------------------
            # Um registro pode possuir várias URLs externas.
            # ------------------------------------------------

            for access_url in access_urls:
                print(
                    f"Tentando: "
                    f"{access_url}"
                )

                result = (
                    process_repository_url(
                        source_url=access_url,
                        record_id=record_id,
                        page=page,
                        session=session,
                    )
                )

                final_result = result

                if result[
                    "success"
                ]:
                    break

                # Restrições não devem ser contornadas.
                if result[
                    "reason"
                ] in {
                    "restricted_or_embargo",
                    "anti_bot",
                }:
                    break

            if (
                final_result
                and final_result[
                    "success"
                ]
            ):
                downloaded_now += 1

                entry = {
                    "record_id": record_id,
                    "status": "downloaded",
                    "reason": (
                        final_result[
                            "reason"
                        ]
                    ),
                    "source_url": (
                        final_result[
                            "source_url"
                        ]
                    ),
                    "pdf_url": (
                        final_result[
                            "pdf_url"
                        ]
                    ),
                    "pdf_path": (
                        final_result[
                            "path"
                        ]
                    ),
                }

                print(
                    "PDF obtido."
                )

            else:
                reason = (
                    final_result[
                        "reason"
                    ]
                    if final_result
                    else "pdf_not_found"
                )

                entry = {
                    "record_id": record_id,
                    "status": "failed",
                    "reason": reason,
                    "source_url": (
                        final_result[
                            "source_url"
                        ]
                        if final_result
                        else None
                    ),
                    "pdf_url": None,
                    "pdf_path": None,
                }

                failures.append(
                    entry
                )

                print(
                    f"Falha: {reason}"
                )

            manifest.append(
                entry
            )

            # Salva progresso após cada documento.
            save_json(
                DOWNLOAD_MANIFEST_FILE,
                manifest,
            )

        browser.close()

    session.close()

    save_json(
        DOWNLOAD_MANIFEST_FILE,
        manifest,
    )

    save_json(
        FAILED_DOWNLOADS_FILE,
        failures,
    )

    print(
        "\n"
        + "=" * 60
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
        f"{already_existing}"
    )

    print(
        f"Falhas: "
        f"{len(failures)}"
    )

    print(
        f"Total de PDFs: "
        f"{len(list(PDF_DIR.glob('*.pdf')))}"
    )


if __name__ == "__main__":
    run()