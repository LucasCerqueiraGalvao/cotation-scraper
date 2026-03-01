from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Tuple

PROJECT_ROOT = Path(__file__).resolve().parents[2]
LOG_DIR = PROJECT_ROOT / "artifacts" / "logs"
SCREENS_DIR = PROJECT_ROOT / "screens"

PARALLEL_STAGE = {
    "hapag": PROJECT_ROOT / "src" / "scrapers" / "hapag_instant_quote.py",
    "maersk": PROJECT_ROOT / "src" / "scrapers" / "maersk_instant_quote.py",
}

SEQUENTIAL_STAGE = {
    "comparison": PROJECT_ROOT / "src" / "processing" / "quote_comparison.py",
    "upload": PROJECT_ROOT / "src" / "export" / "upload_fretes.py",
}


def now_ts() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def build_run_id() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def log(msg: str, summary_log: Path) -> None:
    line = f"[{now_ts()}] {msg}"
    print(line, flush=True)
    with summary_log.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def reset_screens_dir(summary_log: Path) -> None:
    if SCREENS_DIR.exists():
        shutil.rmtree(SCREENS_DIR)
        log(f"[cleanup] pasta removida: {SCREENS_DIR}", summary_log)

    SCREENS_DIR.mkdir(parents=True, exist_ok=True)
    log(f"[cleanup] pasta pronta: {SCREENS_DIR}", summary_log)


def cleanup_old_logs(summary_log: Path, keep_days: int) -> None:
    if keep_days <= 0:
        log(f"[cleanup] retencao de logs desativada (LOG_RETENTION_DAYS={keep_days}).", summary_log)
        return

    cutoff = datetime.now() - timedelta(days=keep_days)
    removed = 0
    failed = 0

    for path in LOG_DIR.iterdir():
        if not path.is_file() or path.suffix.lower() != ".log":
            continue
        if path == summary_log:
            continue

        try:
            file_time = datetime.fromtimestamp(path.stat().st_mtime)
            if file_time < cutoff:
                path.unlink()
                removed += 1
        except Exception:
            failed += 1

    log(
        f"[cleanup] logs antigos removidos={removed}, falhas={failed}, retencao={keep_days} dias.",
        summary_log,
    )


def run_blocking(name: str, script_path: Path, log_path: Path, summary_log: Path, dry_run: bool = False) -> int:
    if not script_path.exists():
        raise FileNotFoundError(f"Script nao encontrado: {script_path}")

    cmd = [sys.executable, str(script_path)]
    log(f"[{name}] iniciando: {' '.join(cmd)}", summary_log)

    if dry_run:
        log(f"[{name}] dry-run: nao executado.", summary_log)
        return 0

    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)

    with log_path.open("a", encoding="utf-8") as lf:
        lf.write(f"[{now_ts()}] CMD: {' '.join(cmd)}\n")
        lf.flush()

        completed = subprocess.run(
            cmd,
            cwd=str(PROJECT_ROOT),
            stdout=lf,
            stderr=subprocess.STDOUT,
            check=False,
            text=True,
            creationflags=creationflags,
        )

    log(f"[{name}] finalizado com codigo {completed.returncode}", summary_log)
    return int(completed.returncode)


def run_parallel_stage(summary_log: Path, run_id: str, dry_run: bool = False) -> Dict[str, int]:
    processes: Dict[str, Tuple[subprocess.Popen[str], object]] = {}
    results: Dict[str, int] = {}

    for name, script_path in PARALLEL_STAGE.items():
        if not script_path.exists():
            raise FileNotFoundError(f"Script nao encontrado: {script_path}")

        cmd = [sys.executable, str(script_path)]
        log_path = LOG_DIR / f"{run_id}_{name}.log"

        log(f"[{name}] iniciando em paralelo: {' '.join(cmd)}", summary_log)

        if dry_run:
            results[name] = 0
            log(f"[{name}] dry-run: nao executado.", summary_log)
            continue

        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        lf = log_path.open("a", encoding="utf-8")
        lf.write(f"[{now_ts()}] CMD: {' '.join(cmd)}\n")
        lf.flush()

        proc = subprocess.Popen(
            cmd,
            cwd=str(PROJECT_ROOT),
            stdout=lf,
            stderr=subprocess.STDOUT,
            text=True,
            creationflags=creationflags,
        )
        processes[name] = (proc, lf)

    for name, pair in processes.items():
        proc, lf = pair
        rc = proc.wait()
        lf.flush()
        lf.close()
        results[name] = int(rc)
        log(f"[{name}] finalizado com codigo {rc}", summary_log)

    return results


def main() -> int:
    parser = argparse.ArgumentParser(description="Executa pipeline diario de cotacoes.")
    parser.add_argument("--dry-run", action="store_true", help="Mostra a orquestracao sem executar scripts.")
    args = parser.parse_args()
    log_retention_days = int(os.getenv("LOG_RETENTION_DAYS", "14"))

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    run_id = build_run_id()
    summary_log = LOG_DIR / f"{run_id}_pipeline.log"

    log("Pipeline iniciado.", summary_log)
    reset_screens_dir(summary_log)
    cleanup_old_logs(summary_log, keep_days=log_retention_days)

    parallel_results = run_parallel_stage(summary_log=summary_log, run_id=run_id, dry_run=args.dry_run)
    parallel_failed = {k: v for k, v in parallel_results.items() if v != 0}

    if parallel_failed:
        log(f"Falha na etapa paralela: {parallel_failed}", summary_log)
        log("Pipeline encerrado com erro.", summary_log)
        return 1

    for name, script_path in SEQUENTIAL_STAGE.items():
        script_log = LOG_DIR / f"{run_id}_{name}.log"
        rc = run_blocking(name=name, script_path=script_path, log_path=script_log, summary_log=summary_log, dry_run=args.dry_run)
        if rc != 0:
            log(f"Falha na etapa {name}.", summary_log)
            log("Pipeline encerrado com erro.", summary_log)
            return 1

    log("Pipeline concluido com sucesso.", summary_log)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
