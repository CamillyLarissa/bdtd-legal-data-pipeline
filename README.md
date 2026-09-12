# BDTD Legal Data Pipeline

Pipeline de engenharia de dados para coleta e preparação de
teses e dissertações da área de Direito da Biblioteca Digital
Brasileira de Teses e Dissertações (BDTD).

## Arquitetura

BDTD → Raw → Staging → Processed → Curated

### Raw
Documentos e metadados originais.

### Staging
Textos extraídos e dados intermediários.

### Processed
Dados padronizados, normalizados, deduplicados e anonimizados.

### Curated
Datasets preparados para:
- pré-treino continuado;
- fine-tuning;
- RAG;
- benchmarks.

## Crawler BDTD

O crawler coleta teses e dissertações da área de Direito. A consulta permanece
equivalente a `lookfor=Direito&type=AllFields` e o fluxo é:

```text
search_records → record_urls.json → extract_metadata → records/*.json
→ downloader → pdf/*.pdf + manifests/*.json
```

Os dados Raw ficam em `data/raw`: URLs e metadados em `metadata`, documentos
em `pdf` e resultados em `manifests`. PDFs válidos e metadados existentes não
são sobrescritos.

Variáveis: `BDTD_DATA_DIR` (padrão `data`), `BDTD_QUERY` (padrão `Direito`),
`BDTD_MAX_RECORDS` (padrão `100`), `BDTD_HEADLESS` (padrão `false`), além dos
timeouts e retries definidos em `src.config`.

Execução local, a partir da raiz:

```powershell
python -m src.crawler.search_records
python -m src.crawler.extract_metadata
python -m src.crawler.downloader
```

No Google Colab, monte o Drive e configure o ambiente antes de importar
`src.config`:

```python
from google.colab import drive
drive.mount("/content/drive")

import os
os.environ["BDTD_DATA_DIR"] = "/content/drive/MyDrive/btd-legal/data"
os.environ["BDTD_QUERY"] = "Direito"
os.environ["BDTD_MAX_RECORDS"] = "100"
os.environ["BDTD_HEADLESS"] = "true"
```

Na raiz do repositório, execute os mesmos comandos com `!python`. Os dados
ficam no Drive, não no GitHub; o mount pertence ao notebook. CAPTCHA, WAF,
anti-bot, acesso restrito e embargo não são contornados, apenas registrados
nos manifests.
