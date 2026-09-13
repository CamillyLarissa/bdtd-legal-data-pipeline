# BDTD Legal Data Pipeline

Pipeline de engenharia de dados para coleta, processamento e preparação de teses e dissertações da área de **Direito** disponíveis na Biblioteca Digital Brasileira de Teses e Dissertações (BDTD).

O projeto organiza os documentos em uma arquitetura de dados em camadas, preservando os dados originais e realizando transformações progressivas até a geração de conjuntos preparados para aplicações de Inteligência Artificial.

## Objetivo

O objetivo do projeto é construir um pipeline reproduzível para:

- coletar teses e dissertações da BDTD;
- armazenar documentos e metadados originais;
- extrair o conteúdo textual dos PDFs;
- padronizar e normalizar os textos;
- identificar documentos duplicados;
- anonimizar informações sensíveis;
- preparar conjuntos de dados para continued pretraining;
- preparar conjuntos para fine-tuning;
- produzir corpus para RAG e busca semântica;
- construir um benchmark para avaliação de modelos.

---

## Arquitetura

O pipeline segue uma arquitetura de dados em quatro camadas:

```text
BDTD
  ↓
Raw
  ↓
Staging
  ↓
Processed
  ↓
Curated
```

Cada camada utiliza como entrada os resultados da camada anterior, sem sobrescrever os dados intermediários.

### Raw

Armazena os dados obtidos diretamente durante a coleta.

Inclui:

- URLs dos registros encontrados;
- metadados das teses e dissertações;
- arquivos PDF disponíveis;
- manifests com informações sobre os downloads e falhas encontradas.

Os dados originais são preservados para permitir rastreabilidade e reprocessamento.

### Staging

Responsável pela conversão dos documentos PDF para uma representação textual estruturada.

O texto é extraído página por página utilizando **PyMuPDF** e armazenado em arquivos JSON, preservando informações como número da página e conteúdo textual.

Essa camada funciona como preparação para as etapas posteriores de tratamento.

### Processed

Responsável pelo tratamento e preparação dos textos extraídos.

O processamento é realizado sequencialmente em quatro etapas:

```text
Staging
   ↓
Padronização
   ↓
Normalização
   ↓
Deduplicação
   ↓
Anonimização
```

#### Padronização

Uniformiza a representação textual dos documentos.

Entre as operações realizadas estão:

- normalização Unicode NFC;
- normalização de quebras de linha;
- remoção de caracteres de controle;
- tratamento de tabs e espaços;
- remoção de espaços excessivos.

#### Normalização

Realiza transformações linguísticas para aproximar palavras de suas formas canônicas.

A etapa utiliza **spaCy** com o modelo de língua portuguesa `pt_core_news_sm`.

A estrutura dos documentos e a paginação são preservadas durante o processamento.

#### Deduplicação

Identifica documentos potencialmente duplicados por similaridade textual.

São utilizados:

- tokenização;
- shingles de palavras;
- MinHash;
- Locality Sensitive Hashing (LSH);
- similaridade de Jaccard.

A implementação utiliza a biblioteca **datasketch**.

#### Anonimização

Responsável pelo tratamento de informações sensíveis identificadas nos documentos antes da geração dos conjuntos finais da camada Curated.

---

## Curated

A camada **Curated** organiza os dados processados em conjuntos específicos para diferentes aplicações de Inteligência Artificial.

A partir dos documentos tratados são produzidos datasets para:

```text
Curated
├── pretraining
├── finetuning
├── rag
└── benchmark
```

### Continued Pretraining

Prepara um corpus textual para possível treinamento continuado de modelos de linguagem sobre documentos do domínio jurídico.

### Fine-tuning

Organiza exemplos em formato adequado para treinamento supervisionado ou ajuste de modelos de linguagem.

### RAG

Prepara os documentos para aplicações de **Retrieval-Augmented Generation (RAG)** e busca semântica.

Os textos são divididos em chunks de até **500 palavras**, com sobreposição de **50 palavras**, mantendo metadados que permitem rastrear a origem do conteúdo.

Entre os metadados preservados estão:

- identificador do documento;
- título;
- autor;
- instituição;
- ano;
- página;
- índice do chunk.

O corpus resultante é armazenado em:

```text
data/curated/rag/corpus_busca.parquet
```

### Benchmark

Constrói um pequeno conjunto de avaliação baseado nos documentos jurídicos processados.

O processo é dividido em três etapas:

```text
Documentos processados
        ↓
Seleção de candidatos
        ↓
Curadoria das questões
        ↓
Construção do benchmark
        ↓
Validação estrutural
```

O módulo de seleção identifica trechos candidatos dos documentos.

Após a análise dos trechos, são construídas manualmente questões de **QA factual**, com gabarito e informações de rastreabilidade.

O benchmark final é armazenado em:

```text
data/curated/benchmark/benchmark.jsonl
```

A etapa de validação verifica a estrutura das instâncias, campos obrigatórios, identificadores e níveis de dificuldade.

---

## Estrutura do projeto

```text
bdtd-legal-data-pipeline/
├── README.md
├── requirements.txt
├── .gitignore
│
└── src/
    ├── __init__.py
    ├── config.py
    ├── pipeline_metrics.py
    │
    ├── crawler/
    │   ├── __init__.py
    │   ├── browser_test.py
    │   ├── search_records.py
    │   ├── inspect_record.py
    │   ├── extract_metadata.py
    │   ├── downloader.py
    │   ├── download_utils.py
    │   ├── repository_detection.py
    │   └── repository_parser.py
    │
    ├── staging/
    │   ├── __init__.py
    │   └── extract_text.py
    │
    ├── processed/
    │   ├── __init__.py
    │   ├── standardize.py
    │   ├── normalize.py
    │   ├── deduplicate.py
    │   └── anonymize.py
    │
    └── curated/
        ├── __init__.py
        ├── pretraining.py
        ├── finetuning.py
        ├── rag.py
        │
        └── benchmark/
            ├── __init__.py
            ├── benchmark.py
            ├── build_benchmark.py
            └── validate_benchmark.py
```

Os dados não são versionados no GitHub devido ao volume dos arquivos. Durante a execução no Google Colab, são armazenados no Google Drive.

---

## Estrutura dos dados

```text
data/
├── raw/
│   ├── metadata/
│   │   ├── record_urls.json
│   │   └── records/
│   ├── pdf/
│   └── manifests/
│
├── staging/
│
├── processed/
│   ├── 01_standardized/
│   ├── 02_normalized/
│   ├── 03_deduplicated/
│   └── 04_anonymized/
│
├── curated/
│   ├── pretraining/
│   ├── finetuning/
│   ├── rag/
│   └── benchmark/
│
└── pipeline_metrics.json
```

---

## Instalação

Clone o repositório:

```bash
git clone <URL_DO_REPOSITORIO>
cd bdtd-legal-data-pipeline
```

Instale as dependências:

```bash
pip install -r requirements.txt
```

Para a etapa de normalização linguística, instale também o modelo de português do spaCy:

```bash
python -m spacy download pt_core_news_sm
```

---

## Configuração

O diretório dos dados e os principais parâmetros podem ser definidos por variáveis de ambiente.

Principais variáveis:

```text
BDTD_DATA_DIR
BDTD_QUERY
BDTD_MAX_RECORDS
BDTD_HEADLESS
```

Valores padrão:

```text
BDTD_DATA_DIR=data
BDTD_QUERY=Direito
BDTD_MAX_RECORDS=100
BDTD_HEADLESS=false
```

---

## Google Colab

Os códigos do projeto ficam no GitHub e os dados de execução são armazenados no Google Drive.

Primeiro, monte o Drive:

```python
from google.colab import drive

drive.mount("/content/drive")
```

Depois configure o ambiente **antes de importar `src.config`**:

```python
import os

os.environ["BDTD_DATA_DIR"] = (
    "/content/drive/MyDrive/bdtd-legal-data/data"
)
os.environ["BDTD_QUERY"] = "Direito"
os.environ["BDTD_MAX_RECORDS"] = "100"
os.environ["BDTD_HEADLESS"] = "true"
```

---

# Execução do Pipeline

## 1. Coleta dos registros

O crawler realiza uma busca ampla pelo termo **Direito** na BDTD, equivalente a:

```text
lookfor=Direito&type=AllFields
```

A primeira etapa coleta os registros encontrados:

```bash
python -m src.crawler.search_records
```

O resultado é armazenado em:

```text
data/raw/metadata/record_urls.json
```

---

## 2. Extração dos metadados

```bash
python -m src.crawler.extract_metadata
```

Os metadados individuais são armazenados em:

```text
data/raw/metadata/records/
```

---

## 3. Download dos documentos

```bash
python -m src.crawler.downloader
```

Os PDFs são armazenados em:

```text
data/raw/pdf/
```

e os resultados das tentativas de download são registrados em:

```text
data/raw/manifests/
```

O crawler não tenta contornar mecanismos de segurança dos repositórios.

Situações como:

- CAPTCHA;
- WAF;
- proteção anti-bot;
- páginas indisponíveis;
- acesso restrito;
- documentos não encontrados;

são registradas para análise.

PDFs válidos já existentes não são sobrescritos desnecessariamente.

---

## 4. Staging — Extração textual

```bash
python -m src.staging.extract_text
```

Essa etapa localiza os PDFs da camada Raw, extrai o texto página por página e gera arquivos JSON estruturados.

---

## 5. Processed — Padronização

```bash
python -m src.processed.standardize
```

---

## 6. Processed — Normalização

```bash
python -m src.processed.normalize
```

---

## 7. Processed — Deduplicação

```bash
python -m src.processed.deduplicate
```

---

## 8. Processed — Anonimização

```bash
python -m src.processed.anonymize
```

Cada etapa utiliza como entrada a saída da etapa anterior, mantendo os resultados intermediários separados.

---

# Execução da camada Curated

## Continued Pretraining

```bash
python -m src.curated.pretraining
```

## Fine-tuning

```bash
python -m src.curated.finetuning
```

## RAG

```bash
python -m src.curated.rag
```

O resultado principal é:

```text
data/curated/rag/corpus_busca.parquet
```

---

## Benchmark

### Seleção de candidatos

```bash
python -m src.curated.benchmark.benchmark
```

Essa etapa seleciona trechos candidatos dos documentos para posterior curadoria.

O resultado é armazenado em:

```text
data/curated/benchmark/candidates.json
```

### Construção do benchmark

Após a análise e curadoria dos candidatos:

```bash
python -m src.curated.benchmark.build_benchmark
```

O conjunto final é salvo em:

```text
data/curated/benchmark/benchmark.jsonl
```

### Validação

```bash
python -m src.curated.benchmark.validate_benchmark
```

A validação verifica a consistência estrutural do dataset antes de seu uso em avaliações de modelos.

---

# Métricas do Pipeline

O projeto também possui uma etapa para consolidar métricas das diferentes camadas.

Execute:

```bash
python -m src.pipeline_metrics
```

O script contabiliza informações como:

- registros coletados;
- PDFs baixados;
- taxa de download;
- documentos extraídos;
- taxa de extração;
- documentos padronizados;
- documentos normalizados;
- documentos únicos após deduplicação;
- duplicados identificados;
- documentos anonimizados;
- chunks preparados para RAG;
- questões do benchmark.

As métricas consolidadas são armazenadas em:

```text
data/pipeline_metrics.json
```

Isso permite executar novamente o pipeline com uma quantidade maior de documentos e atualizar automaticamente os resultados.

---

## Tecnologias utilizadas

O projeto utiliza principalmente:

- **Python** — implementação do pipeline;
- **Playwright** — navegação necessária durante a coleta;
- **PyMuPDF** — extração de texto dos PDFs;
- **spaCy** — processamento e normalização linguística;
- **datasketch** — MinHash e LSH para deduplicação;
- **pandas** — manipulação dos datasets;
- **PyArrow/Parquet** — armazenamento do corpus para RAG;
- **Google Colab** — ambiente de execução;
- **Google Drive** — armazenamento dos dados;
- **GitHub** — versionamento do código.

---

## Reprodutibilidade e preservação dos dados

O pipeline foi desenvolvido seguindo uma organização incremental.

Cada camada:

1. lê os dados da camada anterior;
2. realiza apenas as transformações correspondentes à sua responsabilidade;
3. grava os resultados em um novo diretório;
4. preserva os dados das etapas anteriores.

Dessa forma, é possível analisar as transformações realizadas, executar novamente uma etapa específica e comparar os resultados sem modificar os dados originais.

---

## Limitações

A BDTD agrega documentos provenientes de diferentes instituições e repositórios. Por isso, não existe uma única estrutura de página para todos os registros.

Alguns documentos podem não ser obtidos devido a:

- mecanismos anti-bot;
- páginas de validação de segurança;
- restrições de acesso;
- indisponibilidade do repositório;
- mudanças na estrutura das páginas;
- documentos divididos em múltiplos arquivos;
- ausência de PDF acessível.

Essas situações são tratadas como limitações da coleta e registradas pelo pipeline quando possível.

Além disso, alguns PDFs podem ser constituídos principalmente por imagens ou apresentar problemas de extração textual. Nesses casos, o documento pode permanecer registrado na camada Raw mesmo que não seja utilizado nas etapas textuais posteriores.

---

## Fluxo resumido

```text
                 BDTD
                   │
                   ▼
                 RAW
        ┌──────────┴──────────┐
     Metadados              PDFs
                              │
                              ▼
                           STAGING
                      Extração de texto
                              │
                              ▼
                          PROCESSED
                              │
                     ┌────────┴────────┐
                     │ Padronização    │
                     │ Normalização    │
                     │ Deduplicação    │
                     │ Anonimização    │
                     └────────┬────────┘
                              │
                              ▼
                           CURATED
                ┌─────────────┼─────────────┐
                │             │             │
          Pretraining    Fine-tuning       RAG
                                            │
                                      corpus_busca
                                            │
                                      Benchmark
                                   perguntas/gabaritos
```

## Observação

Os arquivos de dados gerados durante o pipeline não são armazenados no repositório GitHub. O GitHub mantém o código-fonte e os arquivos necessários para reprodução do processamento, enquanto os documentos e datasets são armazenados externamente devido ao seu volume.