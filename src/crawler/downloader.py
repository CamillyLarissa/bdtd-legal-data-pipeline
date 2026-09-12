"""
Downloader dos PDFs associados aos registros da BDTD.

Entrada:
    data/raw/metadata/records/*.json

Saída:
    data/raw/pdf/<record_id>.pdf

Manifestos:
    data/raw/manifests/download_manifest.json
    data/raw/manifests/download_failures.json

Esta etapa pertence à camada Raw do pipeline.

Responsabilidades deste arquivo:
    - percorrer os metadados coletados;
    - obter as URLs de acesso;
    - chamar repository_parser.process_repository_url();
    - salvar o resultado do download;
    - registrar sucessos e falhas.

A descoberta específica do PDF dentro de cada repositório
fica em repository_parser.py.
"""

import json
from pathlib import Path

from playwright.sync_api import sync_playwright

from src.config import (
    BDTD_HEADLESS,
    MANIFEST_DIR,
    METADATA_DIR,
    PDF_DIR,
    create_directories,
)

from src.crawler.repository_parser import (
    process_repository_url,
)


# ============================================================
# Arquivos de manifesto
# ============================================================

DOWNLOAD_MANIFEST_FILE = (
    MANIFEST_DIR
    / "download_manifest.json"
)

DOWNLOAD_FAILURES_FILE = (
    MANIFEST_DIR
    / "download_failures.json"
)


# ============================================================
# Utilidades
# ============================================================


def load_json(
    file_path: Path,
):
    """
    Lê um arquivo JSON.
    """

    with open(
        file_path,
        "r",
        encoding="utf-8",
    ) as file:
        return json.load(file)


def save_json(
    file_path: Path,
    data,
) -> None:
    """
    Salva dados em JSON.
    """

    file_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    with open(
        file_path,
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
    Converte access_url para uma lista de URLs.

    Atualmente o extract_metadata deve produzir apenas uma URL,
    mas esta função mantém compatibilidade com registros antigos
    que possam possuir múltiplas URLs separadas por quebra de linha.

    Exemplos:

        "https://repositorio.exemplo/handle/123"

    retorna:

        [
            "https://repositorio.exemplo/handle/123"
        ]

    E:

        "url1\\nurl2"

    retorna:

        [
            "url1",
            "url2"
        ]
    """

    if value is None:
        return []

    # Caso algum metadata já possua lista.
    if isinstance(
        value,
        list,
    ):
        raw_values = value

    else:
        raw_values = str(
            value
        ).splitlines()

    urls = []
    seen = set()

    for raw_url in raw_values:

        if raw_url is None:
            continue

        url = str(
            raw_url
        ).strip()

        if not url:
            continue

        if not url.startswith(
            (
                "http://",
                "https://",
            )
        ):
            continue

        if url in seen:
            continue

        seen.add(
            url
        )

        urls.append(
            url
        )

    return urls


def get_metadata_files() -> list[Path]:
    """
    Retorna os JSONs individuais de metadata.
    """

    if not METADATA_DIR.exists():
        return []

    return sorted(
        METADATA_DIR.glob(
            "*.json"
        )
    )


def create_manifest_entry(
    record_id: str,
    status: str,
    reason=None,
    source_url=None,
    pdf_url=None,
    pdf_path=None,
) -> dict:
    """
    Cria uma entrada padronizada para o manifesto.
    """

    return {
        "record_id": record_id,
        "status": status,
        "reason": reason,
        "source_url": source_url,
        "pdf_url": pdf_url,
        "pdf_path": (
            str(pdf_path)
            if pdf_path
            else None
        ),
    }


# ============================================================
# Execução
# ============================================================


def run() -> None:
    """
    Executa o download dos PDFs disponíveis.

    Cada metadata deve possuir:

        record_id
        access_url

    O PDF é salvo como:

        data/raw/pdf/<record_id>.pdf
    """

    create_directories()

    metadata_files = (
        get_metadata_files()
    )

    print(
        "Metadados encontrados:",
        len(metadata_files),
    )

    if not metadata_files:
        print(
            "Nenhum metadata encontrado."
        )
        return

    manifest = []
    failures = []

    downloaded_now = 0
    already_existing = 0
    failed = 0

    # --------------------------------------------------------
    # Playwright
    # --------------------------------------------------------

    with sync_playwright() as playwright:

        browser = (
            playwright.chromium.launch(
                headless=BDTD_HEADLESS,
            )
        )

        context = browser.new_context(
            viewport={
                "width": 1440,
                "height": 900,
            },
            accept_downloads=True,
        )

        page = context.new_page()

        # ----------------------------------------------------
        # Processamento dos registros
        # ----------------------------------------------------

        for index, metadata_file in enumerate(
            metadata_files,
            start=1,
        ):

            print()
            print(
                "=" * 60
            )

            try:
                metadata = load_json(
                    metadata_file
                )

            except Exception as error:

                print(
                    f"[{index}/"
                    f"{len(metadata_files)}] "
                    f"Erro ao ler metadata: "
                    f"{error}"
                )

                failed += 1

                entry = (
                    create_manifest_entry(
                        record_id=(
                            metadata_file.stem
                        ),
                        status="failed",
                        reason=(
                            "metadata_read_error"
                        ),
                    )
                )

                manifest.append(
                    entry
                )

                failures.append(
                    entry
                )

                save_json(
                    DOWNLOAD_MANIFEST_FILE,
                    manifest,
                )

                save_json(
                    DOWNLOAD_FAILURES_FILE,
                    failures,
                )

                continue

            # ------------------------------------------------
            # Identificação
            # ------------------------------------------------

            record_id = (
                metadata.get(
                    "record_id"
                )
                or metadata_file.stem
            )

            print(
                f"[{index}/"
                f"{len(metadata_files)}] "
                f"{record_id}"
            )

            pdf_path = (
                PDF_DIR
                / f"{record_id}.pdf"
            )

            # ------------------------------------------------
            # PDF já existente
            # ------------------------------------------------

            if pdf_path.exists():

                already_existing += 1

                entry = (
                    create_manifest_entry(
                        record_id=record_id,
                        status=(
                            "already_exists"
                        ),
                        pdf_path=pdf_path,
                    )
                )

                manifest.append(
                    entry
                )

                save_json(
                    DOWNLOAD_MANIFEST_FILE,
                    manifest,
                )

                print(
                    "PDF já existe."
                )

                continue

            # ------------------------------------------------
            # URLs externas
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

                entry = (
                    create_manifest_entry(
                        record_id=record_id,
                        status="failed",
                        reason="no_access_url",
                    )
                )

                manifest.append(
                    entry
                )

                failures.append(
                    entry
                )

                save_json(
                    DOWNLOAD_MANIFEST_FILE,
                    manifest,
                )

                save_json(
                    DOWNLOAD_FAILURES_FILE,
                    failures,
                )

                print(
                    "Nenhuma URL de acesso."
                )

                continue

            # ------------------------------------------------
            # Tenta cada URL do registro
            # ------------------------------------------------

            final_result = None

            for access_url in access_urls:

                print(
                    f"Tentando: "
                    f"{access_url}"
                )

                try:

                    result = (
                        process_repository_url(
                            page=page,
                            context=context,
                            repository_url=(
                                access_url
                            ),
                            output_file=(
                                pdf_path
                            ),
                        )
                    )

                except Exception as error:

                    print(
                        "Erro durante "
                        "processamento do "
                        "repositório:",
                        error,
                    )

                    result = {
                        "success": False,
                        "reason": (
                            "repository_error"
                        ),
                        "source_url": (
                            access_url
                        ),
                        "pdf_url": None,
                        "path": None,
                    }

                final_result = (
                    result
                )

                # --------------------------------------------
                # Download realizado
                # --------------------------------------------

                if result.get(
                    "success"
                ):
                    break

                # --------------------------------------------
                # Não tentar contornar bloqueios/restrições
                # --------------------------------------------

                if result.get(
                    "reason"
                ) in {
                    "restricted_or_embargo",
                    "anti_bot",
                }:
                    break

            # ------------------------------------------------
            # Sucesso
            # ------------------------------------------------

            if (
                final_result
                and final_result.get(
                    "success"
                )
            ):

                downloaded_now += 1

                saved_path = (
                    final_result.get(
                        "path"
                    )
                    or pdf_path
                )

                entry = (
                    create_manifest_entry(
                        record_id=record_id,
                        status="downloaded",
                        reason=(
                            final_result.get(
                                "reason"
                            )
                        ),
                        source_url=(
                            final_result.get(
                                "source_url"
                            )
                        ),
                        pdf_url=(
                            final_result.get(
                                "pdf_url"
                            )
                        ),
                        pdf_path=(
                            saved_path
                        ),
                    )
                )

                manifest.append(
                    entry
                )

                print(
                    "PDF baixado."
                )

                print(
                    "Arquivo:",
                    saved_path,
                )

            # ------------------------------------------------
            # Falha
            # ------------------------------------------------

            else:

                failed += 1

                if final_result:

                    reason = (
                        final_result.get(
                            "reason"
                        )
                        or "unknown_error"
                    )

                    source_url = (
                        final_result.get(
                            "source_url"
                        )
                    )

                    pdf_url = (
                        final_result.get(
                            "pdf_url"
                        )
                    )

                else:

                    reason = (
                        "no_download_attempt"
                    )

                    source_url = None
                    pdf_url = None

                entry = (
                    create_manifest_entry(
                        record_id=record_id,
                        status="failed",
                        reason=reason,
                        source_url=(
                            source_url
                        ),
                        pdf_url=(
                            pdf_url
                        ),
                    )
                )

                manifest.append(
                    entry
                )

                failures.append(
                    entry
                )

                print(
                    "Falha:"
                )

                print(
                    "Motivo:",
                    reason,
                )

            # ------------------------------------------------
            # Salva progresso a cada registro
            # ------------------------------------------------

            save_json(
                DOWNLOAD_MANIFEST_FILE,
                manifest,
            )

            save_json(
                DOWNLOAD_FAILURES_FILE,
                failures,
            )

        # ----------------------------------------------------
        # Encerramento Playwright
        # ----------------------------------------------------

        context.close()
        browser.close()

    # ========================================================
    # Resultado final
    # ========================================================

    print()
    print(
        "=" * 60
    )

    print(
        "DOWNLOAD FINALIZADO"
    )

    print(
        "Baixados agora:",
        downloaded_now,
    )

    print(
        "Já existentes:",
        already_existing,
    )

    print(
        "Falhas:",
        failed,
    )

    print(
        "Total de PDFs:",
        len(
            list(
                PDF_DIR.glob(
                    "*.pdf"
                )
            )
        ),
    )

    print(
        "Manifesto:",
        DOWNLOAD_MANIFEST_FILE,
    )

    print(
        "Falhas:",
        DOWNLOAD_FAILURES_FILE,
    )


if __name__ == "__main__":
    run()