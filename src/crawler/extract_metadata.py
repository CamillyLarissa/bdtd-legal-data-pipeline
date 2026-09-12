"""
Extrai metadados das páginas de registros da BDTD.

Entrada:
    data/raw/metadata/record_urls.json

Saída:
    data/raw/metadata/records/<record_id>.json

Esta etapa pertence à camada Raw. Os dados são preservados o mais
próximo possível da fonte, sem normalizações semânticas.
"""

import json
import re
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright

from src.config import (
    BDTD_HEADLESS,
    RECORD_URLS_FILE,
    METADATA_DIR,
    create_directories,
)


def normalize_space(value: str | None) -> str | None:
    if value is None:
        return None

    value = re.sub(r"\s+", " ", value).strip()

    return value or None


def extract_record_id(record_url: str) -> str:
    """
    Extrai o identificador a partir da URL do registro.

    Exemplo:
    https://bdtd.ibict.br/vufind/Record/UFSC_abc123
        ->
    UFSC_abc123
    """
    return record_url.rstrip("/").split("/")[-1]


def extract_title(page) -> str | None:
    """
    O título principal do trabalho normalmente aparece em um h1.
    """
    selectors = [
        "h1",
        ".record-title",
        ".title",
    ]

    for selector in selectors:
        locator = page.locator(selector)

        if locator.count() > 0:
            text = normalize_space(
                locator.first.inner_text()
            )

            if text:
                return text

    return None


def extract_access_url(page) -> str | None:
    """
    Obtém somente o link referente ao documento/repositório.

    Não coleta links institucionais, GOV.BR, redes sociais etc.
    """

    links = page.locator("a")

    # Primeira estratégia:
    # procura explicitamente o link "Acessar documento".
    for index in range(links.count()):
        link = links.nth(index)

        try:
            text = normalize_space(
                link.inner_text()
            ) or ""

            href = link.get_attribute("href")

        except Exception:
            continue

        if not href:
            continue

        text_lower = text.lower()

        if (
            "acessar documento" in text_lower
            or "acesso ao documento" in text_lower
            or "visualizar documento" in text_lower
        ):
            return href.strip()

    # Fallback:
    # procura links externos que não sejam infraestrutura do próprio IBICT.
    ignored_domains = {
        "bdtd.ibict.br",
        "ibict.br",
        "www.ibict.br",
        "gov.br",
        "www.gov.br",
        "brasil.gov.br",
        "www4.planalto.gov.br",
        "translate.google.com",
        "linkedin.com",
        "www.linkedin.com",
    }

    for index in range(links.count()):
        link = links.nth(index)

        href = link.get_attribute("href")

        if not href:
            continue

        href = href.strip()

        if not href.startswith(
            ("http://", "https://")
        ):
            continue

        try:
            domain = (
                urlparse(href)
                .netloc
                .lower()
            )
        except Exception:
            continue

        if domain in ignored_domains:
            continue

        # Repositórios acadêmicos costumam aparecer
        # em links contendo handle, repository,
        # repositorio, tese etc.
        href_lower = href.lower()

        indicators = [
            "handle",
            "repositorio",
            "repository",
            "teses",
            "tede",
            ".pdf",
        ]

        if any(
            indicator in href_lower
            for indicator in indicators
        ):
            return href

    return None


def extract_field_from_text(
    body_text: str,
    labels: list[str],
) -> str | None:
    """
    Procura um campo no texto renderizado da página.

    Evita correspondências parciais como:
        "Ano" -> "Ano da publicação"

    exigindo o nome completo do rótulo.
    """

    lines = [
        normalize_space(line)
        for line in body_text.splitlines()
    ]

    lines = [
        line
        for line in lines
        if line
    ]

    for index, line in enumerate(lines):
        for label in labels:
            label_pattern = re.escape(label)

            # Caso:
            # Ano da publicação: 1983
            match = re.match(
                rf"^{label_pattern}\s*:\s*(.+)$",
                line,
                flags=re.IGNORECASE,
            )

            if match:
                return normalize_space(
                    match.group(1)
                )

            # Caso:
            # Ano da publicação
            # 1983
            if re.fullmatch(
                rf"{label_pattern}\s*:?",
                line,
                flags=re.IGNORECASE,
            ):
                if index + 1 < len(lines):
                    return normalize_space(
                        lines[index + 1]
                    )

    return None


def extract_abstract(
    body_text: str,
) -> str | None:
    """
    Extrai o resumo sem confundir com elementos da interface.
    """

    lines = [
        normalize_space(line)
        for line in body_text.splitlines()
    ]

    lines = [
        line
        for line in lines
        if line
    ]

    start_labels = {
        "resumo",
        "resumo em português",
    }

    stop_labels = {
        "abstract",
        "assunto",
        "palavras-chave",
        "autor",
        "autor(a)",
        "orientador",
        "orientador(a)",
        "tipo de documento",
        "ano da publicação",
        "idioma",
        "instituição",
        "programa de pós-graduação",
        "departamento",
        "país",
        "acesso ao documento",
    }

    for index, line in enumerate(lines):
        normalized = (
            line.lower()
            .rstrip(":")
            .strip()
        )

        if normalized not in start_labels:
            continue

        collected = []

        for next_line in lines[
            index + 1 :
        ]:
            normalized_next = (
                next_line.lower()
                .rstrip(":")
                .strip()
            )

            if normalized_next in stop_labels:
                break

            collected.append(next_line)

        abstract = normalize_space(
            " ".join(collected)
        )

        if abstract:
            return abstract

    return None


def extract_metadata_from_page(
    page,
    record_url: str,
) -> dict:
    """
    Extrai os principais metadados do registro.
    """

    body_text = page.locator(
        "body"
    ).inner_text()

    record_id = extract_record_id(
        record_url
    )

    metadata = {
        "record_id": record_id,
        "source": "BDTD",
        "record_url": record_url,
        "title": extract_title(page),
        "year": extract_field_from_text(
            body_text,
            [
                "Ano da publicação",
                "Ano de publicação",
            ],
        ),
        "author": extract_field_from_text(
            body_text,
            [
                "Autor",
                "Autor(a)",
            ],
        ),
        "advisor": extract_field_from_text(
            body_text,
            [
                "Orientador",
                "Orientador(a)",
            ],
        ),
        "document_type": extract_field_from_text(
            body_text,
            [
                "Tipo de documento",
            ],
        ),
        "access_type": extract_field_from_text(
            body_text,
            [
                "Tipo de acesso",
                "Tipo de Acesso",
            ],
        ),
        "language": extract_field_from_text(
            body_text,
            [
                "Idioma",
            ],
        ),
        "institution": extract_field_from_text(
            body_text,
            [
                "Instituição de defesa",
                "Instituição",
            ],
        ),
        "graduate_program": extract_field_from_text(
            body_text,
            [
                "Programa de Pós-Graduação",
            ],
        ),
        "department": extract_field_from_text(
            body_text,
            [
                "Departamento",
            ],
        ),
        "country": extract_field_from_text(
            body_text,
            [
                "País",
            ],
        ),
        "access_url": extract_access_url(
            page
        ),
        "abstract": extract_abstract(
            body_text
        ),
    }

    return metadata


def load_record_urls() -> list[str]:
    """
    Lê record_urls.json.

    Aceita tanto o formato atual:
        {"record_urls": [...]}

    quanto uma lista antiga:
        [...]
    """

    if not RECORD_URLS_FILE.exists():
        raise FileNotFoundError(
            f"Arquivo não encontrado: "
            f"{RECORD_URLS_FILE}"
        )

    with open(
        RECORD_URLS_FILE,
        "r",
        encoding="utf-8",
    ) as file:
        data = json.load(file)

    if isinstance(data, list):
        return data

    if isinstance(data, dict):
        urls = data.get(
            "record_urls",
            [],
        )

        if isinstance(urls, list):
            return urls

    raise ValueError(
        "Formato inválido em "
        f"{RECORD_URLS_FILE}"
    )


def save_metadata(
    metadata: dict,
) -> Path:
    """
    Salva um registro individual em JSON.
    """

    record_id = metadata[
        "record_id"
    ]

    output_file = (
        METADATA_DIR
        / f"{record_id}.json"
    )

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


def run() -> None:
    create_directories()

    record_urls = load_record_urls()

    print(
        "Registros encontrados:",
        len(record_urls),
    )

    success = 0
    errors = 0

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=BDTD_HEADLESS,
        )

        context = browser.new_context(
            viewport={
                "width": 1440,
                "height": 900,
            }
        )

        page = context.new_page()

        for index, record_url in enumerate(
            record_urls,
            start=1,
        ):
            print()
            print("=" * 60)

            print(
                f"[{index}/{len(record_urls)}]"
            )

            print(record_url)

            try:
                page.goto(
                    record_url,
                    wait_until="domcontentloaded",
                    timeout=60000,
                )

                page.wait_for_timeout(
                    2000
                )

                metadata = (
                    extract_metadata_from_page(
                        page,
                        record_url,
                    )
                )

                output_file = save_metadata(
                    metadata
                )

                success += 1

                print(
                    "Título:",
                    metadata.get(
                        "title"
                    ),
                )

                print(
                    "Acesso:",
                    metadata.get(
                        "access_url"
                    ),
                )

                print(
                    "Salvo:",
                    output_file,
                )

            except Exception as error:
                errors += 1

                print(
                    "Erro:",
                    error,
                )

        context.close()
        browser.close()

    print()
    print("=" * 60)
    print("EXTRAÇÃO FINALIZADA")
    print("Sucesso:", success)
    print("Erros:", errors)


if __name__ == "__main__":
    run()