import json
import re
import time
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright


INPUT_FILE = Path("data/raw/metadata/record_urls.json")
OUTPUT_DIR = Path("data/raw/metadata/records")

MAX_RECORDS = 100


def load_record_urls():
    with open(INPUT_FILE, "r", encoding="utf-8") as file:
        return json.load(file)


def get_record_id(url):
    """
    Extrai o identificador do registro a partir da URL.

    Exemplo:
    https://bdtd.ibict.br/vufind/Record/UFSC_xxx

    retorna:
    UFSC_xxx
    """
    return url.rstrip("/").split("/")[-1]


def clean_value(value):
    if value is None:
        return None

    value = value.strip()

    if not value:
        return None

    if value.lower() == "não informado pela instituição":
        return None

    return value


def extract_field(text, label, next_labels):
    """
    Extrai um campo usando os rótulos presentes
    no texto renderizado da página.

    Exemplo:
    Ano de defesa:1983
    Autor(a) principal:
    Cleve, Clemerson Merlin
    """

    escaped_label = re.escape(label)

    next_pattern = "|".join(
        re.escape(item)
        for item in next_labels
    )

    pattern = (
        rf"{escaped_label}\s*:?\s*"
        rf"(.*?)"
        rf"(?=\n(?:{next_pattern})\s*:?|$)"
    )

    match = re.search(
        pattern,
        text,
        flags=re.DOTALL | re.IGNORECASE,
    )

    if not match:
        return None

    value = match.group(1).strip()

    return clean_value(value)


def extract_metadata(page, record_url):
    body_text = page.locator("body").inner_text()

    labels = [
        "Ano de defesa",
        "Autor(a) principal",
        "Orientador(a)",
        "Banca de defesa",
        "Tipo de documento",
        "Tipo de acesso",
        "Idioma",
        "Instituição de defesa",
        "Programa de Pós-Graduação",
        "Departamento",
        "País",
        "Link de acesso",
        "Resumo",
        "Metadados do item",
    ]

    title = page.locator("h1").first.inner_text().strip()

    if not title:
        title = page.title()

    year = extract_field(
        body_text,
        "Ano de defesa",
        labels,
    )

    author = extract_field(
        body_text,
        "Autor(a) principal",
        labels,
    )

    advisor = extract_field(
        body_text,
        "Orientador(a)",
        labels,
    )

    document_type = extract_field(
        body_text,
        "Tipo de documento",
        labels,
    )

    access_type = extract_field(
        body_text,
        "Tipo de acesso",
        labels,
    )

    language = extract_field(
        body_text,
        "Idioma",
        labels,
    )

    institution = extract_field(
        body_text,
        "Instituição de defesa",
        labels,
    )

    graduate_program = extract_field(
        body_text,
        "Programa de Pós-Graduação",
        labels,
    )

    department = extract_field(
        body_text,
        "Departamento",
        labels,
    )

    country = extract_field(
        body_text,
        "País",
        labels,
    )

    access_url = extract_field(
        body_text,
        "Link de acesso",
        labels,
    )

    abstract = extract_field(
        body_text,
        "Resumo",
        labels,
    )

    record_id = get_record_id(record_url)

    return {
        "record_id": record_id,
        "source": "BDTD",
        "record_url": record_url,
        "title": clean_value(title),
        "year": clean_value(year),
        "author": clean_value(author),
        "advisor": clean_value(advisor),
        "document_type": clean_value(document_type),
        "access_type": clean_value(access_type),
        "language": clean_value(language),
        "institution": clean_value(institution),
        "graduate_program": clean_value(graduate_program),
        "department": clean_value(department),
        "country": clean_value(country),
        "access_url": clean_value(access_url),
        "abstract": clean_value(abstract),
    }


def save_metadata(metadata):
    OUTPUT_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    record_id = metadata["record_id"]

    output_file = OUTPUT_DIR / f"{record_id}.json"

    with open(
        output_file,
        "w",
        encoding="utf-8",
    ) as file:
        json.dump(
            metadata,
            file,
            ensure_ascii=False,
            indent=2,
        )

    return output_file


def crawl_metadata():
    record_urls = load_record_urls()

    record_urls = record_urls[:MAX_RECORDS]

    print(
        f"Quantidade de registros para processar: "
        f"{len(record_urls)}"
    )

    success = 0
    errors = 0

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False
        )

        page = browser.new_page()

        for index, record_url in enumerate(
            record_urls,
            start=1,
        ):
            print("\n" + "=" * 60)
            print(
                f"[{index}/{len(record_urls)}] "
                f"{record_url}"
            )

            try:
                page.goto(
                    record_url,
                    wait_until="domcontentloaded",
                    timeout=60000,
                )

                page.wait_for_timeout(1500)

                metadata = extract_metadata(
                    page,
                    record_url,
                )

                output_file = save_metadata(
                    metadata
                )

                success += 1

                print(
                    f"Título: {metadata['title']}"
                )

                print(
                    f"Ano: {metadata['year']}"
                )

                print(
                    f"Tipo: {metadata['document_type']}"
                )

                print(
                    f"Link: {metadata['access_url']}"
                )

                print(
                    f"Salvo em: {output_file}"
                )

            except Exception as error:
                errors += 1

                print(
                    f"ERRO: {error}"
                )

            time.sleep(0.5)

        browser.close()

    print("\n" + "=" * 60)
    print("EXTRAÇÃO FINALIZADA")
    print(f"Sucesso: {success}")
    print(f"Erros: {errors}")


if __name__ == "__main__":
    crawl_metadata()