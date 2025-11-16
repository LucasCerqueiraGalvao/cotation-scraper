import subprocess
from pathlib import Path
import sys

scripts = [
    ("cma", "cma_instant_quote_batch.py"),
    ("hapag", "hapag_instant_quote.py"),
    ("maersk", "maersk_instant_quote.py")
]

base = Path(__file__).resolve().parent
python = base / ".venv" / "Scripts" / "python.exe"

for name, script in scripts:
    log_file = base / "logs" / f"{name}.log"
    log_file.parent.mkdir(exist_ok=True)
    subprocess.Popen(
        [str(python), str(base / script)],
        stdout=open(log_file, "w"),
        stderr=subprocess.STDOUT
    )

print("Scrapers iniciados. Logs em /logs")
