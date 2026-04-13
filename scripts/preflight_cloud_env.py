from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(PROJECT_ROOT / ".env", override=False)


def resolve_env_path(env_name: str, default_path: Path) -> Path:
    raw = os.getenv(env_name)
    if not raw:
        return default_path
    p = Path(raw).expanduser()
    if not p.is_absolute():
        p = PROJECT_ROOT / p
    return p


def truthy(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "t", "yes", "y", "on"}


def print_ok(msg: str) -> None:
    print(f"[OK] {msg}")


def print_warn(msg: str) -> None:
    print(f"[WARN] {msg}")


def print_fail(msg: str) -> None:
    print(f"[FAIL] {msg}")


def check_required_env(names: list[str]) -> list[str]:
    missing: list[str] = []
    for name in names:
        if not (os.getenv(name) or "").strip():
            missing.append(name)
    return missing


def can_write_dir(path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".preflight_write_probe.tmp"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        return True
    except Exception:
        return False


def main() -> int:
    failures = 0
    warnings = 0

    print("=== Preflight Cloud Env ===")
    print(f"PROJECT_ROOT={PROJECT_ROOT}")

    py = sys.version_info
    if (py.major, py.minor) >= (3, 10):
        print_ok(f"Python version {py.major}.{py.minor} compatible (>= 3.10)")
    else:
        failures += 1
        print_fail(f"Python version {py.major}.{py.minor} incompatible (need >= 3.10)")

    upload_mode = (os.getenv("UPLOAD_MODE") or "SYNC").strip().upper()
    valid_upload_mode = {"SYNC", "SHAREPOINT", "BOTH"}
    if upload_mode in valid_upload_mode:
        print_ok(f"UPLOAD_MODE={upload_mode}")
    else:
        failures += 1
        print_fail(f"UPLOAD_MODE invalido: {upload_mode} (validos: {sorted(valid_upload_mode)})")

    base_missing = check_required_env(["HL_USER", "HL_PASS", "MAERSK_USER", "MAERSK_PASS"])
    if base_missing:
        failures += 1
        print_fail(f"Credenciais obrigatorias ausentes: {base_missing}")
    else:
        print_ok("Credenciais base de scraper presentes (HL/MAERSK)")

    # Manual quotation files (current behavior still reads local files)
    manual_quotes_source = (os.getenv("MANUAL_QUOTES_SOURCE") or "FILES").strip().upper()
    cma_file = resolve_env_path(
        "CMA_COTATIONS_FILE",
        PROJECT_ROOT / "artifacts" / "input" / "cma_cotations.xlsx",
    )
    one_file = resolve_env_path(
        "ONE_COTATIONS_FILE",
        cma_file.parent / "one_cotations.xlsx",
    )
    zim_file = resolve_env_path(
        "ZIM_COTATIONS_FILE",
        cma_file.parent / "zim_cotations.xlsx",
    )

    if manual_quotes_source == "GRAPH":
        warnings += 1
        print_warn(
            "MANUAL_QUOTES_SOURCE=GRAPH: validacao de existencia local de cma/one/zim foi ignorada."
        )
    else:
        missing_files = [str(p) for p in [cma_file, one_file, zim_file] if not p.exists()]
        if missing_files:
            failures += 1
            print_fail("Planilhas manuais ausentes: " + ", ".join(missing_files))
        else:
            print_ok("Planilhas manuais cma/one/zim acessiveis")

    # Upload checks
    if upload_mode in {"SHAREPOINT", "BOTH"}:
        sp_missing = check_required_env(
            ["SHAREPOINT_TENANT_ID", "SHAREPOINT_CLIENT_ID", "SHAREPOINT_CLIENT_SECRET"]
        )
        site_id = (os.getenv("SHAREPOINT_SITE_ID") or "").strip()
        host = (os.getenv("SHAREPOINT_HOSTNAME") or "").strip()
        site_path = (os.getenv("SHAREPOINT_SITE_PATH") or "").strip()
        site_ok = bool(site_id) or (bool(host) and bool(site_path))

        if sp_missing:
            failures += 1
            print_fail(f"Segredos SharePoint ausentes: {sp_missing}")
        else:
            print_ok("Credenciais SharePoint principais presentes")

        if site_ok:
            print_ok("Configuracao de site SharePoint presente (SITE_ID ou HOSTNAME+SITE_PATH)")
        else:
            failures += 1
            print_fail(
                "Configuracao de site SharePoint ausente (defina SHAREPOINT_SITE_ID "
                "ou SHAREPOINT_HOSTNAME + SHAREPOINT_SITE_PATH)"
            )

    if upload_mode in {"SYNC", "BOTH"}:
        sync_folder = resolve_env_path(
            "SYNC_FOLDER",
            PROJECT_ROOT / "artifacts" / "sync_out",
        )
        if can_write_dir(sync_folder):
            print_ok(f"SYNC_FOLDER gravavel: {sync_folder}")
        else:
            failures += 1
            print_fail(f"SYNC_FOLDER nao gravavel: {sync_folder}")

        if truthy(os.getenv("UPLOAD_ENSURE_ONEDRIVE"), default=True):
            warnings += 1
            print_warn(
                "UPLOAD_ENSURE_ONEDRIVE=TRUE: em cloud, preferir FALSE quando UPLOAD_MODE=SHAREPOINT."
            )

    artifacts_dirs = [
        PROJECT_ROOT / "artifacts" / "output",
        PROJECT_ROOT / "artifacts" / "logs",
        PROJECT_ROOT / "artifacts" / "runtime",
    ]
    for p in artifacts_dirs:
        if can_write_dir(p):
            print_ok(f"Diretorio gravavel: {p}")
        else:
            failures += 1
            print_fail(f"Diretorio nao gravavel: {p}")

    print("--- Summary ---")
    print(f"failures={failures}")
    print(f"warnings={warnings}")

    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())

