import json
from pathlib import Path

from src.config import BENCHMARK_DIR


REQUIRED_FIELDS = {
    "id",
    "task",
    "question",
    "answer",
    "record_id",
    "title",
    "page",
    "difficulty",
}


def load_benchmark(path: Path) -> list[dict]:
    """Carrega as instâncias do benchmark em formato JSONL."""
    items = []

    with path.open("r", encoding="utf-8") as f:
        for line_number, line in enumerate(f, start=1):
            line = line.strip()

            if not line:
                continue

            try:
                item = json.loads(line)
                items.append(item)

            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"JSON inválido na linha {line_number}: {exc}"
                ) from exc

    return items


def validate_item(item: dict, index: int):
    """Valida os campos obrigatórios de uma instância."""
    missing = REQUIRED_FIELDS - item.keys()

    if missing:
        raise ValueError(
            f"Instância {index} possui campos ausentes: "
            f"{sorted(missing)}"
        )

    for field in [
        "id",
        "task",
        "question",
        "answer",
        "record_id",
        "title",
        "difficulty",
    ]:
        if not item[field]:
            raise ValueError(
                f"Instância {index}: campo '{field}' está vazio."
            )

    if not isinstance(item["page"], int):
        raise ValueError(
            f"Instância {index}: 'page' deve ser inteiro."
        )

    if item["difficulty"] not in {
        "easy",
        "medium",
        "hard",
    }:
        raise ValueError(
            f"Instância {index}: dificuldade inválida."
        )


def main():
    benchmark_file = BENCHMARK_DIR / "benchmark.jsonl"

    if not benchmark_file.exists():
        raise FileNotFoundError(
            f"Benchmark não encontrado: {benchmark_file}"
        )

    items = load_benchmark(benchmark_file)

    if not items:
        raise ValueError(
            "O benchmark não possui nenhuma instância."
        )

    ids = set()

    for index, item in enumerate(items, start=1):
        validate_item(item, index)

        if item["id"] in ids:
            raise ValueError(
                f"ID duplicado: {item['id']}"
            )

        ids.add(item["id"])

    documents = {
        item["record_id"]
        for item in items
    }

    difficulties = {}

    for item in items:
        difficulty = item["difficulty"]

        difficulties[difficulty] = (
            difficulties.get(difficulty, 0) + 1
        )

    summary = {
        "task": "qa_factual",
        "instances": len(items),
        "documents": len(documents),
        "difficulty_distribution": difficulties,
        "format": "jsonl",
        "split": "test",
        "status": "validated",
    }

    summary_file = (
        BENCHMARK_DIR / "benchmark_final_summary.json"
    )

    with summary_file.open(
        "w",
        encoding="utf-8",
    ) as f:
        json.dump(
            summary,
            f,
            ensure_ascii=False,
            indent=2,
        )

    print("=" * 60)
    print("BENCHMARK VALIDADO")
    print(f"Questões: {len(items)}")
    print(f"Documentos utilizados: {len(documents)}")
    print(f"Dificuldades: {difficulties}")
    print("Erros: 0")
    print(f"Arquivo: {benchmark_file}")


if __name__ == "__main__":
    main()