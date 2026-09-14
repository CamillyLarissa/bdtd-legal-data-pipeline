"""
Extração robusta dos metadados bibliográficos da BDTD.

Entrada:
    data/raw/metadata/record_urls.json

Saída:
    data/raw/metadata/records/<record_id>.json
    data/raw/metadata/failed_metadata.json

Características:
- preserva metadados válidos já existentes;
- reprocessa somente arquivos ausentes ou inválidos;
- faz múltiplas tentativas;
- aguarda o carregamento real dos metadados;
- não salva páginas vazias como sucesso;
- mantém compatibilidade com o downloader.
"""

import json
import os
import random
import re
import time
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright

from src.config import (
    RECORD_URLS_FILE,
    METADATA_DIR,
    create_directories,
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
        "true",
    ).lower()
    == "true"
)

MAX_RETRIES = 4

PAGE_TIMEOUT = 60000

METADATA_WAIT_TIMEOUT = 15000

WAIT_BETWEEN_RETRIES = 7

MIN_WAIT_BETWEEN_RECORDS = 2.0

MAX_WAIT_BETWEEN_RECORDS = 4.0


# ============================================================
# JSON
# ============================================================

def load_json(path: Path):
    with path.open(
        "r",
        encoding="utf-8",
    ) as file:
        return json.load(file)


def save_json(
    path: Path,
    data,
):
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


# ============================================================
# UTILITÁRIOS
# ============================================================

def normalize_space(
    value,
):
    if value is None:
        return None

    value = re.sub(
        r"\s+",
        " ",
        str(value),
    ).strip()

    return value or None


def extract_record_id(
    record_url,
):
    parsed = urlparse(
        record_url
    )

    path = parsed.path.rstrip("/")

    record_id = (
        path.split("/")[-1]
    )

    return re.sub(
        r"[^A-Za-z0-9_.-]",
        "_",
        record_id,
    )


# ============================================================
# URLS DOS REGISTROS
# ============================================================

def load_record_urls():
    if not RECORD_URLS_FILE.exists():
        raise FileNotFoundError(
            f"Arquivo não encontrado: "
            f"{RECORD_URLS_FILE}"
        )

    data = load_json(
        RECORD_URLS_FILE
    )

    if isinstance(
        data,
        list,
    ):
        urls = data

    elif isinstance(
        data,
        dict,
    ):
        urls = data.get(
            "record_urls",
            [],
        )

    else:
        raise ValueError(
            "Formato inválido em "
            f"{RECORD_URLS_FILE}"
        )

    return urls[:MAX_RECORDS]


# ============================================================
# QUALIDADE DO METADATA
# ============================================================

def metadata_is_valid(
    metadata,
):
    """
    Considera válido quando pelo menos dois dos três
    campos principais foram extraídos.

    Isso evita salvar páginas vazias, mas permite casos
    raros em que a instituição não informou algum campo.
    """

    if not isinstance(
        metadata,
        dict,
    ):
        return False

    important = [
        metadata.get("title"),
        metadata.get("year"),
        metadata.get("author"),
    ]

    filled = sum(
        bool(normalize_space(value))
        for value in important
    )

    return filled >= 2


def existing_metadata_is_valid(
    path,
):
    if not path.exists():
        return False

    try:
        metadata = load_json(path)

        return metadata_is_valid(
            metadata
        )

    except Exception:
        return False


# ============================================================
# LINHAS DA PÁGINA
# ============================================================

def get_page_lines(
    page,
):
    try:
        body = (
            page.locator("body")
            .inner_text()
        )

    except Exception:
        return []

    result = []

    for line in body.splitlines():

        line = normalize_space(
            line
        )

        if line:
            result.append(
                line
            )

    return result


# ============================================================
# RÓTULOS CONHECIDOS
# ============================================================

KNOWN_LABELS = [
    "Ano de defesa",
    "Ano de publicação",
    "Autor(a) principal",
    "Autor principal",
    "Orientador(a)",
    "Orientador",
    "Banca de defesa",
    "Tipo de documento",
    "Tipo de acesso",
    "Idioma",
    "Instituição de defesa",
    "Instituição",
    "Programa de Pós-Graduação",
    "Programa de Pós Graduação",
    "Departamento",
    "País",
    "Link de acesso",
    "URL de acesso",
    "Resumo",
]


def looks_like_label(
    value,
):
    if not value:
        return False

    normalized = (
        normalize_space(value)
        .lower()
    )

    for label in KNOWN_LABELS:

        label_lower = (
            label.lower()
        )

        if (
            normalized
            == label_lower
            or normalized
            == f"{label_lower}:"
        ):
            return True

        if normalized.startswith(
            f"{label_lower}:"
        ):
            return True

    return False


# ============================================================
# EXTRAÇÃO DE CAMPO
# ============================================================

def extract_field(
    lines,
    labels,
):
    """
    Suporta:

        Ano de defesa: 2024

    e:

        Ano de defesa:
        2024
    """

    for index, line in enumerate(
        lines
    ):

        for label in labels:

            # -----------------------------------------------
            # Campo e valor na mesma linha
            # -----------------------------------------------

            pattern = (
                rf"^{re.escape(label)}"
                rf"\s*:\s*(.+)$"
            )

            match = re.match(
                pattern,
                line,
                flags=re.IGNORECASE,
            )

            if match:

                value = normalize_space(
                    match.group(1)
                )

                # Evita algo como:
                # Instituição:
                # Programa de Pós-Graduação: ...
                if (
                    value
                    and not looks_like_label(
                        value
                    )
                ):
                    return value

            # -----------------------------------------------
            # Rótulo em uma linha e valor na próxima
            # -----------------------------------------------

            only_label = (
                rf"^{re.escape(label)}"
                rf"\s*:\s*$"
            )

            if re.match(
                only_label,
                line,
                flags=re.IGNORECASE,
            ):

                if index + 1 >= len(lines):
                    continue

                value = normalize_space(
                    lines[index + 1]
                )

                if (
                    value
                    and not looks_like_label(
                        value
                    )
                ):
                    return value

    return None


# ============================================================
# TÍTULO
# ============================================================

def extract_title(
    page,
    lines,
):
    selectors = [
        "h1",
        ".record-title",
        ".title",
    ]

    for selector in selectors:

        try:

            locator = page.locator(
                selector
            )

            if locator.count() == 0:
                continue

            text = normalize_space(
                locator.first.inner_text()
            )

            if (
                text
                and len(text) > 5
                and text.lower()
                not in {
                    "metadados do item",
                    "detalhes bibliográficos",
                }
            ):
                return text

        except Exception:
            continue

    # --------------------------------------------------------
    # Fallback:
    # linha imediatamente anterior ao Ano de defesa
    # --------------------------------------------------------

    for index, line in enumerate(
        lines
    ):

        lower = line.lower()

        if (
            lower.startswith(
                "ano de defesa"
            )
            or lower.startswith(
                "ano de publicação"
            )
        ):

            if index > 0:

                candidate = (
                    normalize_space(
                        lines[index - 1]
                    )
                )

                if (
                    candidate
                    and not looks_like_label(
                        candidate
                    )
                ):
                    return candidate

    return None


# ============================================================
# LINKS EXTERNOS
# ============================================================

def extract_access_url(
    page,
    lines,
    record_url,
):
    """
    Primeiro tenta o campo textual 'Link de acesso'.

    Caso não exista, procura links externos candidatos.
    """

    textual_url = extract_field(
        lines,
        [
            "Link de acesso",
            "URL de acesso",
        ],
    )

    if (
        textual_url
        and textual_url.startswith(
            (
                "http://",
                "https://",
            )
        )
    ):
        return textual_url

    record_host = (
        urlparse(
            record_url
        ).netloc
    )

    ignored = [
        "facebook.com",
        "twitter.com",
        "x.com/",
        "instagram.com",
        "linkedin.com",
        "creativecommons.org",
        "google.com",
    ]

    try:
        locator = page.locator(
            "a[href]"
        )

        count = locator.count()

    except Exception:
        return None

    candidates = []

    for index in range(
        count
    ):

        try:
            href = (
                locator.nth(index)
                .get_attribute("href")
            )

        except Exception:
            continue

        if not href:
            continue

        if not href.startswith(
            (
                "http://",
                "https://",
            )
        ):
            continue

        parsed = urlparse(
            href
        )

        if (
            parsed.netloc
            == record_host
        ):
            continue

        lower = href.lower()

        if any(
            item in lower
            for item in ignored
        ):
            continue

        if href not in candidates:
            candidates.append(
                href
            )

    if not candidates:
        return None

    # Prioriza links que parecem repositórios acadêmicos.
    preferred_terms = [
        "handle",
        "hdl.handle.net",
        "repositorio",
        "repository",
        "tede",
        "dspace",
        ".pdf",
        "teses",
        "dissert",
        "maxwell",
        "archivum",
    ]

    for url in candidates:

        lower = url.lower()

        if any(
            term in lower
            for term in preferred_terms
        ):
            return url

    return candidates[0]


# ============================================================
# LIMPEZA DE VALORES AUSENTES
# ============================================================

def clean_value(
    value,
):
    value = normalize_space(
        value
    )

    if value is None:
        return None

    normalized = (
        value.lower()
    )

    missing = {
        "não informado",
        "não informado pela instituição",
        "nao informado",
        "nao informado pela instituicao",
        "não disponível",
        "nao disponivel",
        "[s.n.]",
        "-",
    }

    if normalized in missing:
        return None

    return value


# ============================================================
# ESPERA PELOS METADADOS
# ============================================================

def wait_for_metadata(
    page,
):
    """
    Espera até a página realmente apresentar metadados
    bibliográficos.

    Retorna False quando a página não carregou corretamente.
    """

    try:

        page.wait_for_function(
            """
            () => {
                const text =
                    (document.body?.innerText || '')
                    .toLowerCase();

                return (
                    text.includes('ano de defesa') ||
                    text.includes('ano de publicação')
                ) && (
                    text.includes('autor(a) principal') ||
                    text.includes('autor principal')
                );
            }
            """,
            timeout=METADATA_WAIT_TIMEOUT,
        )

        return True

    except Exception:
        return False


# ============================================================
# DETECÇÃO DE BLOQUEIO
# ============================================================

def detect_bad_page(
    page,
):
    try:

        text = (
            page.locator("body")
            .inner_text()
            .lower()
        )

    except Exception:
        return "empty_page"

    bad_terms = [
        "too many requests",
        "access denied",
        "verificação de segurança",
        "verificacao de seguranca",
        "captcha",
        "temporarily unavailable",
        "service unavailable",
        "erro 429",
    ]

    for term in bad_terms:

        if term in text:
            return term

    if len(text.strip()) < 100:
        return "empty_or_incomplete_page"

    return None


# ============================================================
# EXTRAÇÃO DO REGISTRO
# ============================================================

def extract_record_metadata(
    page,
    record_url,
):
    lines = get_page_lines(
        page
    )

    metadata = {
        "record_id": (
            extract_record_id(
                record_url
            )
        ),

        "source": "BDTD",

        "record_url": record_url,

        "title": extract_title(
            page,
            lines,
        ),

        "year": extract_field(
            lines,
            [
                "Ano de defesa",
                "Ano de publicação",
            ],
        ),

        "author": extract_field(
            lines,
            [
                "Autor(a) principal",
                "Autor principal",
                "Autor(a)",
                "Autor",
            ],
        ),

        "advisor": extract_field(
            lines,
            [
                "Orientador(a)",
                "Orientador",
            ],
        ),

        "document_type": extract_field(
            lines,
            [
                "Tipo de documento",
            ],
        ),

        "access_type": extract_field(
            lines,
            [
                "Tipo de acesso",
            ],
        ),

        "language": extract_field(
            lines,
            [
                "Idioma",
            ],
        ),

        "institution": extract_field(
            lines,
            [
                "Instituição de defesa",
                "Instituição",
            ],
        ),

        "graduate_program": extract_field(
            lines,
            [
                "Programa de Pós-Graduação",
                "Programa de Pós Graduação",
            ],
        ),

        "department": extract_field(
            lines,
            [
                "Departamento",
            ],
        ),

        "country": extract_field(
            lines,
            [
                "País",
                "Pais",
            ],
        ),

        "access_url": extract_access_url(
            page,
            lines,
            record_url,
        ),

        "abstract": extract_field(
            lines,
            [
                "Resumo",
            ],
        ),
    }

    for key in [
        "title",
        "year",
        "author",
        "advisor",
        "document_type",
        "access_type",
        "language",
        "institution",
        "graduate_program",
        "department",
        "country",
        "access_url",
        "abstract",
    ]:

        metadata[key] = clean_value(
            metadata.get(key)
        )

    return metadata


# ============================================================
# EXECUÇÃO
# ============================================================

def run():
    create_directories()

    record_urls = (
        load_record_urls()
    )

    failed_file = (
        METADATA_DIR.parent
        / "failed_metadata.json"
    )

    print(
        "Registros encontrados:",
        len(record_urls),
    )

    print(
        "Diretório:",
        METADATA_DIR,
    )

    valid_existing = 0
    recovered = 0
    failed_count = 0

    failures = []

    with sync_playwright() as playwright:

        browser = (
            playwright.chromium.launch(
                headless=HEADLESS,
            )
        )

        # ====================================================
        # REGISTROS
        # ====================================================

        for index, record_url in enumerate(
            record_urls,
            start=1,
        ):

            record_id = (
                extract_record_id(
                    record_url
                )
            )

            output_file = (
                METADATA_DIR
                / f"{record_id}.json"
            )

            print()
            print("=" * 70)

            print(
                f"[{index}/"
                f"{len(record_urls)}]"
            )

            print(
                record_id
            )

            # ------------------------------------------------
            # Já existe e está bom
            # ------------------------------------------------

            if existing_metadata_is_valid(
                output_file
            ):

                print(
                    "Metadata válido já existe. Pulando."
                )

                valid_existing += 1
                continue

            # ------------------------------------------------
            # Existe, mas está ruim
            # ------------------------------------------------

            if output_file.exists():

                print(
                    "Metadata existente inválido. "
                    "Será tentado novamente."
                )

            metadata = None

            last_reason = (
                "metadata_not_loaded"
            )

            # ------------------------------------------------
            # Tentativas
            # ------------------------------------------------

            for attempt in range(
                1,
                MAX_RETRIES + 1,
            ):

                print(
                    f"Tentativa "
                    f"{attempt}/"
                    f"{MAX_RETRIES}"
                )

                context = (
                    browser.new_context(
                        ignore_https_errors=True,
                        viewport={
                            "width": 1440,
                            "height": 900,
                        },
                    )
                )

                page = (
                    context.new_page()
                )

                try:

                    page.goto(
                        record_url,
                        wait_until=(
                            "domcontentloaded"
                        ),
                        timeout=PAGE_TIMEOUT,
                    )

                    loaded = (
                        wait_for_metadata(
                            page
                        )
                    )

                    if not loaded:

                        bad_page = (
                            detect_bad_page(
                                page
                            )
                        )

                        last_reason = (
                            bad_page
                            or "metadata_not_loaded"
                        )

                        print(
                            "Página sem metadados:",
                            last_reason,
                        )

                    else:

                        candidate = (
                            extract_record_metadata(
                                page,
                                record_url,
                            )
                        )

                        if metadata_is_valid(
                            candidate
                        ):

                            metadata = (
                                candidate
                            )

                            break

                        last_reason = (
                            "invalid_metadata"
                        )

                        print(
                            "Metadata principal incompleto."
                        )

                except Exception as error:

                    last_reason = (
                        type(error).__name__
                    )

                    print(
                        "Erro:",
                        error,
                    )

                finally:

                    try:
                        context.close()
                    except Exception:
                        pass

                if attempt < MAX_RETRIES:

                    print(
                        f"Aguardando "
                        f"{WAIT_BETWEEN_RETRIES}s..."
                    )

                    time.sleep(
                        WAIT_BETWEEN_RETRIES
                    )

            # ------------------------------------------------
            # SUCESSO
            # ------------------------------------------------

            if metadata:

                save_json(
                    output_file,
                    metadata,
                )

                recovered += 1

                print(
                    "Título:",
                    metadata.get(
                        "title"
                    ),
                )

                print(
                    "Ano:",
                    metadata.get(
                        "year"
                    ),
                )

                print(
                    "Autor:",
                    metadata.get(
                        "author"
                    ),
                )

                print(
                    "Instituição:",
                    metadata.get(
                        "institution"
                    ),
                )

                print(
                    "URL:",
                    metadata.get(
                        "access_url"
                    ),
                )

                print(
                    "SALVO ✅"
                )

            # ------------------------------------------------
            # FALHA
            # ------------------------------------------------

            else:

                failed_count += 1

                # Remove JSON antigo inválido para evitar que
                # outras etapas o interpretem como metadata bom.
                if output_file.exists():

                    try:
                        output_file.unlink()

                    except Exception:
                        pass

                failures.append(
                    {
                        "record_id": (
                            record_id
                        ),
                        "record_url": (
                            record_url
                        ),
                        "reason": (
                            last_reason
                        ),
                    }
                )

                print(
                    "FALHA ❌"
                )

            # Manifesto incremental
            save_json(
                failed_file,
                failures,
            )

            # Intervalo aleatório para reduzir frequência
            # constante de acesso à BDTD.
            time.sleep(
                random.uniform(
                    MIN_WAIT_BETWEEN_RECORDS,
                    MAX_WAIT_BETWEEN_RECORDS,
                )
            )

        browser.close()

    # ========================================================
    # RESULTADO FINAL
    # ========================================================

    total_valid = 0

    for path in (
        METADATA_DIR
        .glob("*.json")
    ):

        if existing_metadata_is_valid(
            path
        ):
            total_valid += 1

    print()
    print("=" * 70)

    print(
        "EXTRAÇÃO FINALIZADA"
    )

    print(
        "Válidos já existentes:",
        valid_existing,
    )

    print(
        "Recuperados nesta execução:",
        recovered,
    )

    print(
        "Falhas:",
        failed_count,
    )

    print(
        "Total de metadados válidos:",
        total_valid,
    )

    print(
        "Falhas salvas em:",
        failed_file,
    )


if __name__ == "__main__":
    run()