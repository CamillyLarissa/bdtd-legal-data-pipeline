"""
Configurações centrais do pipeline BDTD.

Os caminhos dos dados são definidos a partir da variável de ambiente
BDTD_DATA_DIR.

Exemplos:

Execução local:
    BDTD_DATA_DIR não definido
    -> utiliza ./data

Google Colab:
    os.environ["BDTD_DATA_DIR"] = (
        "/content/drive/MyDrive/btd-legal/data"
    )

O objetivo é manter o código independente do ambiente onde está sendo
executado.
"""

import os
from pathlib import Path


# ============================================================
# Funções auxiliares para variáveis de ambiente
# ============================================================

def env_bool(name: str, default: bool) -> bool:
    """
    Lê uma variável de ambiente como booleano.
    """
    value = os.getenv(name)

    if value is None:
        return default

    return value.strip().lower() in {
        "1",
        "true",
        "yes",
        "y",
        "sim",
    }


def env_int(name: str, default: int) -> int:
    """
    Lê uma variável de ambiente como inteiro.
    """
    value = os.getenv(name)

    if value is None:
        return default

    try:
        return int(value)
    except ValueError:
        return default


# ============================================================
# Configuração geral do crawler
# ============================================================

BDTD_QUERY = os.getenv(
    "BDTD_QUERY",
    "Direito",
)

BDTD_MAX_RECORDS = env_int(
    "BDTD_MAX_RECORDS",
    100,
)

BDTD_HEADLESS = env_bool(
    "BDTD_HEADLESS",
    False,
)

REQUEST_TIMEOUT = env_int(
    "BDTD_REQUEST_TIMEOUT",
    20,
)

PAGE_TIMEOUT = env_int(
    "BDTD_PAGE_TIMEOUT",
    30000,
)

MAX_RETRIES = env_int(
    "BDTD_MAX_RETRIES",
    2,
)

# Compatibilidade com módulos antigos do crawler
BDTD_REQUEST_TIMEOUT = REQUEST_TIMEOUT
BDTD_PAGE_TIMEOUT = PAGE_TIMEOUT


# ============================================================
# Diretório principal dos dados
# ============================================================

DATA_DIR = Path(
    os.getenv(
        "BDTD_DATA_DIR",
        "data",
    )
)


# ============================================================
# Camadas principais
# ============================================================

RAW_DIR = DATA_DIR / "raw"
STAGING_DIR = DATA_DIR / "staging"
PROCESSED_DIR = DATA_DIR / "processed"
CURATED_DIR = DATA_DIR / "curated"


# ============================================================
# RAW
# ============================================================

METADATA_ROOT_DIR = RAW_DIR / "metadata"

RECORD_URLS_FILE = (
    METADATA_ROOT_DIR
    / "record_urls.json"
)

METADATA_DIR = (
    METADATA_ROOT_DIR
    / "records"
)

PDF_DIR = RAW_DIR / "pdf"

MANIFEST_DIR = (
    RAW_DIR
    / "manifests"
)


# ============================================================
# PROCESSED
# ============================================================

STANDARDIZED_DIR = (
    PROCESSED_DIR
    / "01_standardized"
)

NORMALIZED_DIR = (
    PROCESSED_DIR
    / "02_normalized"
)

DEDUPLICATED_DIR = (
    PROCESSED_DIR
    / "03_deduplicated"
)

ANONYMIZED_DIR = (
    PROCESSED_DIR
    / "04_anonymized"
)


# ============================================================
# CURATED
# ============================================================

PRETRAINING_DIR = (
    CURATED_DIR
    / "pretraining"
)

FINETUNING_DIR = (
    CURATED_DIR
    / "finetuning"
)

RAG_DIR = (
    CURATED_DIR
    / "rag"
)

BENCHMARK_DIR = (
    CURATED_DIR
    / "benchmark"
)


# ============================================================
# Diretórios que devem existir
# ============================================================

ALL_DIRECTORIES = [
    METADATA_ROOT_DIR,
    METADATA_DIR,
    PDF_DIR,
    MANIFEST_DIR,
    STAGING_DIR,
    STANDARDIZED_DIR,
    NORMALIZED_DIR,
    DEDUPLICATED_DIR,
    ANONYMIZED_DIR,
    PRETRAINING_DIR,
    FINETUNING_DIR,
    RAG_DIR,
    BENCHMARK_DIR,
]


def create_directories() -> None:
    """
    Cria todos os diretórios necessários para o pipeline.

    A função utiliza exist_ok=True, portanto não remove nem
    sobrescreve dados existentes.
    """
    for directory in ALL_DIRECTORIES:
        directory.mkdir(
            parents=True,
            exist_ok=True,
        )


if __name__ == "__main__":
    create_directories()

    print("Estrutura criada.")
    print(f"DATA_DIR: {DATA_DIR}")
    print(f"Consulta: {BDTD_QUERY}")
    print(f"Máximo: {BDTD_MAX_RECORDS}")
    print(f"Headless: {BDTD_HEADLESS}")