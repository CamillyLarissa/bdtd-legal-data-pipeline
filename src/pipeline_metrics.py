import time
import subprocess

tempos = {}

def executar_etapa(nome, comandos):
    inicio = time.perf_counter()

    print("=" * 60)
    print(f"EXECUTANDO: {nome}")
    print("=" * 60)

    for comando in comandos:
        subprocess.run(
            comando,
            shell=True,
            check=True
        )

    fim = time.perf_counter()

    tempo = fim - inicio
    tempos[nome] = tempo

    print(f"\nTempo de {nome}: {tempo:.2f} s\n")