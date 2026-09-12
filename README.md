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
