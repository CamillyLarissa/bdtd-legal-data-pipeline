"""
Orquestrador de download dos PDFs da BDTD.

Entrada:
    data/raw/metadata/record_urls.json
    data/raw/metadata/records/*.json

Saída:
    data/raw/pdf/<record_id>.pdf

Manifestos:
    data/raw/manifests/download_manifest.json
    data/raw/manifests/failed_downloads.json

Responsabilidades:
- carregar somente os registros da coleta atual;
- carregar metadados correspondentes;
- verificar PDFs existentes;
- chamar repository_parser;
- registrar sucessos e falhas;
- preservar resultados incrementalmente.
"""

import json
import os
import re
import time

from pathlib import Path
from urllib.parse import (
    unquote,
    urlparse,
)

from playwright.sync_api import (
    sync_playwright,
)

from src.config import (
    MANIFEST_DIR,
    METADATA_DIR,
    METADATA_ROOT_DIR,
    PDF_DIR,
    RECORD_URLS_FILE,
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
        "2500",
    )
)

HEADLESS = (
    os.getenv(
        "BDTD_HEADLESS",
        "true",
    ).lower()
    == "true"
)

DELAY_BETWEEN_RECORDS = 1


# ============================================================
# JSON
# ============================================================

def load_json(
    path: Path,
):
    """
    Lê JSON.
    """

    with path.open(
        "r",
        encoding="utf-8",
    ) as file:

        return json.load(
            file
        )


def save_json(
    path: Path,
    data,
):
    """
    Salva JSON.
    """

    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    temp_file = (
        path.with_suffix(
            path.suffix + ".tmp"
        )
    )

    with temp_file.open(
        "w",
        encoding="utf-8",
    ) as file:

        json.dump(
            data,
            file,
            ensure_ascii=False,
            indent=2,
        )

    temp_file.replace(
        path
    )


def save_manifest(
    manifest,
):
    """
    Salva manifesto incrementalmente.
    """

    save_json(
        MANIFEST_DIR
        / "download_manifest.json",
        manifest,
    )


# ============================================================
# IDENTIFICAÇÃO DE REGISTROS
# ============================================================

def extract_record_id_from_url(
    url,
):
    """
    Obtém o ID da URL da BDTD.

    Exemplo:

    https://bdtd.ibict.br/vufind/Record/UFT_abc123

        -> UFT_abc123
    """

    if not url:
        return None

    try:
        path = (
            unquote(
                urlparse(
                    str(url)
                ).path
            )
            .rstrip("/")
        )

        parts = path.split("/")

        if "Record" in parts:

            index = (
                parts.index(
                    "Record"
                )
            )

            if (
                index + 1
                < len(parts)
            ):
                return parts[
                    index + 1
                ]

        if parts:
            return parts[-1]

    except Exception:
        pass

    return None


# ============================================================
# CORPUS ATUAL
# ============================================================

def load_current_record_ids():
    """
    Lê record_urls.json e retorna somente IDs
    pertencentes à coleta atual.

    Essa é a fonte oficial do corpus.
    """

    if not RECORD_URLS_FILE.exists():

        print(
            "ATENÇÃO: "
            "record_urls.json não encontrado."
        )

        return []

    try:
        data = load_json(
            RECORD_URLS_FILE
        )

    except Exception as error:

        print(
            "Erro ao ler "
            "record_urls.json:",
            error,
        )

        return []

    if isinstance(
        data,
        list,
    ):
        items = data

    elif isinstance(
        data,
        dict,
    ):
        items = (
            data.get(
                "record_urls",
                [],
            )
        )

    else:
        items = []

    record_ids = []

    seen = set()

    for item in items:

        if isinstance(
            item,
            str,
        ):
            url = item

        elif isinstance(
            item,
            dict,
        ):
            url = (
                item.get("url")
                or item.get(
                    "record_url"
                )
                or item.get(
                    "bdtd_url"
                )
            )

        else:
            continue

        record_id = (
            extract_record_id_from_url(
                url
            )
        )

        if not record_id:
            continue

        if record_id in seen:
            continue

        seen.add(
            record_id
        )

        record_ids.append(
            record_id
        )

        if (
            len(record_ids)
            >= MAX_RECORDS
        ):
            break

    return record_ids


# ============================================================
# METADADOS
# ============================================================

def load_metadata_files():
    """
    Retorna somente os metadados dos registros
    pertencentes ao record_urls.json atual.

    Isso evita misturar arquivos antigos de
    execuções anteriores.
    """

    current_ids = (
        load_current_record_ids()
    )

    # --------------------------------------------------------
    # CORPUS ATUAL ENCONTRADO
    # --------------------------------------------------------

    if current_ids:

        files = []

        missing = []

        for record_id in current_ids:

            metadata_file = (
                METADATA_DIR
                / f"{record_id}.json"
            )

            if metadata_file.exists():

                files.append(
                    metadata_file
                )

            else:
                missing.append(
                    record_id
                )

        print(
            "IDs na coleta atual:",
            len(current_ids),
        )

        print(
            "Metadados disponíveis:",
            len(files),
        )

        print(
            "Metadados ainda faltando:",
            len(missing),
        )

        return files

    # --------------------------------------------------------
    # FALLBACK
    # --------------------------------------------------------

    print()
    print(
        "AVISO:"
    )

    print(
        "Não foi possível identificar "
        "o corpus atual pelo "
        "record_urls.json."
    )

    print(
        "Usando todos os metadados "
        "como fallback."
    )

    return sorted(
        METADATA_DIR.glob(
            "*.json"
        )
    )[
        :MAX_RECORDS
    ]


# ============================================================
# URLS
# ============================================================

def split_access_urls(
    value,
):
    """
    Extrai uma ou mais URLs de access_url.

    Compatível com:
    - string;
    - lista;
    - várias URLs separadas por linha.
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

    for item in values:

        matches = re.findall(
            r"https?://[^\s]+",
            str(item),
        )

        for url in matches:

            url = (
                url.strip()
                .rstrip(
                    ".,);]"
                )
            )

            if url not in urls:
                urls.append(
                    url
                )

    return urls


# ============================================================
# PDF EXISTENTE
# ============================================================

def is_valid_existing_pdf(
    path: Path,
):
    """
    Verifica assinatura binária do arquivo PDF.

    Evita considerar páginas HTML salvas
    incorretamente como PDF.
    """

    if not path.exists():
        return False

    if not path.is_file():
        return False

    try:
        if path.stat().st_size < 5:
            return False

        with path.open(
            "rb"
        ) as file:

            header = (
                file.read(8)
            )

        return (
            content_is_pdf_bytes(
                header,
                "",
            )
        )

    except Exception as error:

        print(
            "Erro ao validar PDF:",
            error,
        )

        return False


# ============================================================
# PROCESSAMENTO PRINCIPAL
# ============================================================

def run():
    """
    Executa o downloader.
    """

    create_directories()

    metadata_files = (
        load_metadata_files()
    )

    print()
    print(
        "=" * 70
    )

    print(
        "DOWNLOAD DE PDFs"
    )

    print(
        "=" * 70
    )

    print(
        "Metadados encontrados:",
        len(metadata_files),
    )

    print(
        "PDF_DIR:",
        PDF_DIR,
    )

    print(
        "HEADLESS:",
        HEADLESS,
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
                user_agent=(
                    "Mozilla/5.0 "
                    "(Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 "
                    "(KHTML, like Gecko) "
                    "Chrome/152.0.0.0 "
                    "Safari/537.36"
                ),
            )
        )

        page = (
            context.new_page()
        )

        # ====================================================
        # REGISTROS
        # ====================================================

        for index, metadata_file in enumerate(
            metadata_files,
            start=1,
        ):

            try:
                metadata = load_json(
                    metadata_file
                )

            except Exception as error:

                print()
                print(
                    "=" * 70
                )

                print(
                    f"[{index}/"
                    f"{len(metadata_files)}]"
                )

                print(
                    "Erro ao ler metadado:",
                    metadata_file,
                )

                print(
                    error
                )

                failed += 1

                manifest.append(
                    {
                        "record_id": (
                            metadata_file.stem
                        ),
                        "status": "failed",
                        "reason": (
                            "metadata_read_error"
                        ),
                    }
                )

                save_manifest(
                    manifest
                )

                continue

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

            print()
            print(
                "=" * 70
            )

            print(
                f"[{index}/"
                f"{len(metadata_files)}]"
            )

            print(
                "Registro:",
                record_id,
            )

            # =================================================
            # PDF JÁ EXISTE
            # =================================================

            if output_file.exists():

                if is_valid_existing_pdf(
                    output_file
                ):

                    print(
                        "PDF já existe "
                        "e é válido."
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

                    save_manifest(
                        manifest
                    )

                    continue

                print(
                    "PDF existente inválido."
                )

                print(
                    "Removendo para tentar "
                    "novamente."
                )

                try:
                    output_file.unlink()

                except Exception as error:

                    print(
                        "Não foi possível "
                        "remover:",
                        error,
                    )

                    failed += 1

                    manifest.append(
                        {
                            "record_id": (
                                record_id
                            ),
                            "status": "failed",
                            "reason": (
                                "invalid_existing_pdf"
                            ),
                        }
                    )

                    save_manifest(
                        manifest
                    )

                    continue

            # =================================================
            # URLS DE ACESSO
            # =================================================

            access_urls = (
                split_access_urls(
                    metadata.get(
                        "access_url"
                    )
                )
            )

            if not access_urls:

                print(
                    "Sem URL de acesso."
                )

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

                save_manifest(
                    manifest
                )

                continue

            print(
                "URLs de acesso:",
                len(access_urls),
            )

            success = False

            final_reason = (
                "unknown"
            )

            successful_url = None

            # =================================================
            # TENTA CADA URL
            # =================================================

            for access_url in access_urls:

                print()
                print(
                    "Tentando repositório:"
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

                if result.get(
                    "success"
                ):

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

                # ---------------------------------------------
                # NÃO TENTA CONTORNAR PROTEÇÕES
                # ---------------------------------------------

                if final_reason in {
                    "restricted_or_embargo",
                    "anti_bot",
                }:
                    break

            # =================================================
            # SUCESSO
            # =================================================

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

            # =================================================
            # FALHA
            # =================================================

            else:

                failed += 1

                manifest.append(
                    {
                        "record_id": (
                            record_id
                        ),
                        "status": "failed",
                        "access_urls": (
                            access_urls
                        ),
                        "reason": (
                            final_reason
                        ),
                    }
                )

            # =================================================
            # MANIFESTO INCREMENTAL
            # =================================================

            save_manifest(
                manifest
            )

            time.sleep(
                DELAY_BETWEEN_RECORDS
            )

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

    save_manifest(
        manifest
    )

    # ========================================================
    # CONTAGEM DOS PDFs
    # ========================================================

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
    print(
        "=" * 70
    )

    print(
        "DOWNLOAD FINALIZADO"
    )

    print(
        "=" * 70
    )

    print(
        "Processados:",
        len(metadata_files),
    )

    print(
        "Baixados agora:",
        downloaded_now,
    )

    print(
        "Já existentes:",
        already_exists,
    )

    print(
        "Falhas:",
        failed,
    )

    print(
        "Total de PDFs na pasta:",
        total_pdfs,
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