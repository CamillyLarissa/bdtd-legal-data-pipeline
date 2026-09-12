import json
import time
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from playwright.sync_api import sync_playwright


METADATA_DIR = Path("data/raw/metadata/records")
PDF_DIR = Path("data/raw/pdf")

MAX_RECORDS = 100

DOWNLOAD_TIMEOUT = 60

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 Chrome/120 Safari/537.36"
    )
}


def load_metadata_files():
    return sorted(
        METADATA_DIR.glob("*.json")
    )[:MAX_RECORDS]


def load_metadata(path):
    with open(path, "r", encoding="utf-8") as file:
        return json.load(file)


def looks_like_pdf_url(url):
    if not url:
        return False

    lower = url.lower()

    indicators = [
        ".pdf",
        "/bitstream/",
        "download",
        "arquivo",
        "document",
    ]

    return any(
        indicator in lower
        for indicator in indicators
    )


def find_pdf_link(page, repository_url):
    """
    Procura um possível link de PDF
    na página do repositório institucional.
    """

    links = page.locator("a[href]")

    candidates = []

    for i in range(links.count()):
        link = links.nth(i)

        href = link.get_attribute("href")

        if not href:
            continue

        full_url = urljoin(
            repository_url,
            href,
        )

        try:
            text = link.inner_text().strip()
        except Exception:
            text = ""

        lower_text = text.lower()
        lower_url = full_url.lower()

        score = 0

        if ".pdf" in lower_url:
            score += 10

        if "/bitstream/" in lower_url:
            score += 8

        if "pdf" in lower_text:
            score += 5

        if "download" in lower_text:
            score += 4

        if "baixar" in lower_text:
            score += 4

        if "arquivo" in lower_text:
            score += 3

        if "texto completo" in lower_text:
            score += 3

        if looks_like_pdf_url(full_url):
            score += 2

        if score > 0:
            candidates.append(
                {
                    "url": full_url,
                    "text": text,
                    "score": score,
                }
            )

    if not candidates:
        return None

    candidates.sort(
        key=lambda item: item["score"],
        reverse=True,
    )

    return candidates[0]["url"]


def download_pdf(pdf_url, record_id):
    PDF_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    output_file = (
        PDF_DIR /
        f"{record_id}.pdf"
    )

    try:
        response = requests.get(
            pdf_url,
            headers=HEADERS,
            timeout=DOWNLOAD_TIMEOUT,
            allow_redirects=True,
        )

        response.raise_for_status()

    except requests.RequestException as error:
        print(
            f"Erro durante download: {error}"
        )

        return None

    content_type = (
        response.headers
        .get("Content-Type", "")
        .lower()
    )

    content = response.content

    is_pdf = (
        "application/pdf" in content_type
        or content.startswith(b"%PDF")
    )

    if not is_pdf:
        print(
            "O conteúdo recebido não parece ser PDF."
        )
        return None

    with open(
        output_file,
        "wb",
    ) as file:
        file.write(content)

    return output_file


def run():
    metadata_files = load_metadata_files()

    print(
        f"Registros disponíveis: "
        f"{len(metadata_files)}"
    )

    success = 0
    not_found = 0
    errors = 0

    with sync_playwright() as p:

        browser = p.chromium.launch(
            headless=False
        )

        page = browser.new_page()

        for index, metadata_file in enumerate(
            metadata_files,
            start=1,
        ):
            metadata = load_metadata(
                metadata_file
            )

            record_id = metadata.get(
                "record_id"
            )

            repository_url = metadata.get(
                "access_url"
            )

            print("\n" + "=" * 60)

            print(
                f"[{index}/{len(metadata_files)}]"
            )

            print(
                f"Registro: {record_id}"
            )

            print(
                f"Repositório: {repository_url}"
            )

            if not repository_url:
                print(
                    "Registro sem link de acesso."
                )

                not_found += 1
                continue

            try:
                page.goto(
                    repository_url,
                    wait_until="domcontentloaded",
                    timeout=60000,
                )

                page.wait_for_timeout(2500)

                print(
                    f"Página carregada: "
                    f"{page.title()}"
                )

                pdf_url = find_pdf_link(
                    page,
                    repository_url,
                )

                if not pdf_url:
                    print(
                        "PDF não encontrado."
                    )

                    not_found += 1
                    continue

                print(
                    f"Possível PDF: "
                    f"{pdf_url}"
                )

                output_file = download_pdf(
                    pdf_url,
                    record_id,
                )

                if output_file:
                    success += 1

                    print(
                        f"PDF salvo em: "
                        f"{output_file}"
                    )

                else:
                    errors += 1

            except Exception as error:
                errors += 1

                print(
                    f"Erro: {error}"
                )

            time.sleep(1)

        browser.close()

    print("\n" + "=" * 60)
    print("DOWNLOAD FINALIZADO")
    print(f"PDFs baixados: {success}")
    print(
        f"PDFs não encontrados: "
        f"{not_found}"
    )
    print(f"Erros: {errors}")


if __name__ == "__main__":
    run()