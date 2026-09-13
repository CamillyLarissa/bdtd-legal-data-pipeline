import json

from src.config import BENCHMARK_DIR


BENCHMARK_ITEMS = [
    {
        "id": "legal_qa_001",
        "task": "qa_factual",
        "question": (
            "Qual princípio é apresentado como central para a realização "
            "dos direitos humanos no Direito do Trabalho?"
        ),
        "answer": "O princípio da dignidade da pessoa humana.",
        "record_id": "PUC_MINS_83424040ddcde830666078e850f880f3",
        "title": "O direito do trabalho como dimensão dos direitos humanos",
        "page": 106,
        "difficulty": "easy",
    },
    {
        "id": "legal_qa_002",
        "task": "qa_factual",
        "question": (
            "Segundo o trecho, quais artigos da CLT são utilizados para "
            "caracterizar juridicamente a relação de emprego?"
        ),
        "answer": "Os artigos 2º e 3º da CLT.",
        "record_id": "PUC_MINS_1fbefa79e4b3e25e7ea03f625845e2cb",
        "title": "O direito do trabalho e o direito Eleitoral",
        "page": 44,
        "difficulty": "easy",
    },
    {
        "id": "legal_qa_003",
        "task": "qa_factual",
        "question": (
            "Qual potencial é atribuído ao direito real de laje "
            "no trecho analisado?"
        ),
        "answer": (
            "Aumentar a área habitável e contribuir para a regularização "
            "de favelas e subúrbios, ampliando o acesso à moradia digna "
            "e a outros direitos relacionados."
        ),
        "record_id": "PUC_PR-29_8ca5a8b484f3a5df7c809968e4c2e57d",
        "title": "O direito real de laje como direito à moradia digna",
        "page": 88,
        "difficulty": "medium",
    },
    {
        "id": "legal_qa_004",
        "task": "qa_factual",
        "question": (
            "O que o Supremo Tribunal Federal decidiu na ADC nº 19 "
            "em relação à Lei Maria da Penha?"
        ),
        "answer": (
            "Declarou a constitucionalidade dos artigos 1º, 33 e 41 "
            "da Lei Maria da Penha."
        ),
        "record_id": "UFJF_5146977b0a315f17395bb792468a5a02",
        "title": "Direito à privacidade da mulher e os direitos humanos",
        "page": 53,
        "difficulty": "easy",
    },
    {
        "id": "legal_qa_005",
        "task": "qa_factual",
        "question": (
            "A quem cabe o ônus da prova no processo penal, "
            "segundo o trecho?"
        ),
        "answer": (
            "Cabe à acusação provar os fatos que justificam a condenação."
        ),
        "record_id": "PUC_MINS_e877b94d7e344d8db505a3890268d1a2",
        "title": (
            "Aplicação dos direitos fundamentais no direito penal brasileiro"
            "influência do direito internacional na proteção dos direitos fundamentais"
        ),
        "page": 79,
        "difficulty": "easy",
    },
    {
        "id": "legal_qa_006",
        "task": "qa_factual",
        "question": (
            "Qual é o papel atribuído à Educação em Direitos Humanos "
            "na transformação do currículo?"
        ),
        "answer": (
            "Atuar como ferramenta de transformação do currículo, "
            "empoderando os educandos para compreender e criticar "
            "as relações de poder."
        ),
        "record_id": "UFMG_9f003ac298f7a214213b145981acfd5d",
        "title": "Pelo direito de “educar-se” em direitos humanos",
        "page": 104,
        "difficulty": "medium",
    },
    {
        "id": "legal_qa_007",
        "task": "qa_factual",
        "question": (
            "Segundo a Declaração Universal dos Direitos Humanos citada "
            "no texto, como todos os seres humanos nascem?"
        ),
        "answer": "Livres e iguais em dignidade e direitos.",
        "record_id": "PUC_PR-29_2fbc89a4e2f0963bd9bdad9c02952a40",
        "title": "O ensino dos direitos humanos pelos cursos de direito",
        "page": 22,
        "difficulty": "easy",
    },
    {
        "id": "legal_qa_008",
        "task": "qa_factual",
        "question": (
            "Quais virtudes são apontadas como necessárias para a "
            "participação cidadã no funcionamento da democracia?"
        ),
        "answer": (
            "Patriotismo, postura ativa, espírito público e desejo "
            "de participar dos assuntos políticos."
        ),
        "record_id": "PUC_MINS_9a29cc1159f6bf3d5cc3da35d1c73939",
        "title": (
            "Da era dos direitos à era dos sem direitos"
            "o mito do não retrocesso e a mitigação de direitos"
        ),
        "page": 29,
        "difficulty": "medium",
    },
]


def main():
    """
    Cria o benchmark final em formato JSONL
    a partir das questões curadas manualmente.
    """
    BENCHMARK_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    output_file = BENCHMARK_DIR / "benchmark.jsonl"

    with output_file.open(
        "w",
        encoding="utf-8",
    ) as f:

        for item in BENCHMARK_ITEMS:
            f.write(
                json.dumps(
                    item,
                    ensure_ascii=False,
                )
                + "\n"
            )

    documents = {
        item["record_id"]
        for item in BENCHMARK_ITEMS
    }

    difficulties = {}

    for item in BENCHMARK_ITEMS:
        difficulty = item["difficulty"]

        difficulties[difficulty] = (
            difficulties.get(difficulty, 0) + 1
        )

    print("=" * 60)
    print("BENCHMARK CRIADO")
    print(f"Questões: {len(BENCHMARK_ITEMS)}")
    print(f"Documentos utilizados: {len(documents)}")
    print(f"Dificuldades: {difficulties}")
    print(f"Arquivo: {output_file}")


if __name__ == "__main__":
    main()