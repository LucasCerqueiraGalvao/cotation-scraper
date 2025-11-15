# main.py
import subprocess
import sys
import os
from pathlib import Path

SCRIPTS = [
    "cma_instant_quote.py",
    "hapag_instant_quote.py",
    "maersk_instant_quote.py",
]


def get_python_venv(base_dir: Path) -> str:
    if os.name == "nt":
        candidate = base_dir / ".venv" / "Scripts" / "python.exe"
    else:
        candidate = base_dir / ".venv" / "bin" / "python"
    return str(candidate) if candidate.exists() else sys.executable


def main():
    base_dir = Path(__file__).resolve().parent
    python_exec = get_python_venv(base_dir)

    processes = []

    # inicia todos os scrapers em paralelo
    for script in SCRIPTS:
        script_path = base_dir / script
        if not script_path.exists():
            print(f"[ERRO] Arquivo não encontrado: {script_path}")
            continue

        print(f"Iniciando {script} com {python_exec}")
        p = subprocess.Popen([python_exec, str(script_path)])
        processes.append((script, p))

    # espera todos terminarem
    for script, p in processes:
        ret = p.wait()
        if ret == 0:
            print(f"[OK] {script} finalizado com sucesso.")
        else:
            print(f"[ERRO] {script} terminou com código {ret}.")


if __name__ == "__main__":
    main()
