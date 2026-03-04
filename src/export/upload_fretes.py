import os
from pathlib import Path
import shutil
import subprocess
import time

import pandas as pd
from dotenv import load_dotenv
from openpyxl.styles import Alignment, Font
from openpyxl.worksheet.table import Table, TableStyleInfo

# =========================================
# 1) CONFIGURACOES GERAIS
# =========================================

PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env", override=True)


def resolve_env_path(env_name: str, default_path: Path) -> Path:
    raw = os.getenv(env_name)
    if not raw:
        return default_path

    candidate = Path(raw).expanduser()
    if not candidate.is_absolute():
        candidate = PROJECT_ROOT / candidate
    return candidate

# Arquivos locais (onde o pipeline ja grava o CSV)
CSV_INPUT = PROJECT_ROOT / "artifacts" / "output" / "comparacao_carriers.csv"
XLSX_OUTPUT = PROJECT_ROOT / "artifacts" / "output" / "comparacao_carriers_cliente.xlsx"

# Pasta sincronizada com OneDrive / SharePoint
SYNC_FOLDER = resolve_env_path(
    "SYNC_FOLDER",
    PROJECT_ROOT / "artifacts" / "sync_out",
)

OBSERVACAO_CLIENTE = (
    "Todas as ofertas incluem DTHC nas rotas em que existe aplicacao. "
    "Fretes SPOT estao sujeitos a alteracao sem aviso previo. "
    "Taxa de amend/cancelamento de USD 350,00/container."
)
TABLE_LAST_ROW_MIN = 223
ONEDRIVE_START_TIMEOUT_SEC = int(os.getenv("ONEDRIVE_START_TIMEOUT_SEC", "30"))
UPLOAD_SYNC_WAIT_SEC = int(os.getenv("UPLOAD_SYNC_WAIT_SEC", "30"))
UPLOAD_ENSURE_ONEDRIVE = os.getenv("UPLOAD_ENSURE_ONEDRIVE", "TRUE").strip().lower() in {
    "1", "true", "t", "yes", "y", "on"
}


def _is_any_process_running(process_names):
    for process_name in process_names:
        try:
            result = subprocess.run(
                ["tasklist", "/FI", f"IMAGENAME eq {process_name}"],
                capture_output=True,
                text=True,
                encoding="cp1252",
                errors="ignore",
                check=False,
            )
            if process_name.lower() in (result.stdout or "").lower():
                return True
        except Exception:
            continue
    return False


def _find_onedrive_exe() -> Path | None:
    candidates = [
        Path(os.environ.get("ProgramFiles", "")) / "Microsoft OneDrive" / "OneDrive.exe",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "OneDrive" / "OneDrive.exe",
    ]
    for c in candidates:
        if c.exists():
            return c
    return None


def ensure_onedrive_running(timeout_sec: int = ONEDRIVE_START_TIMEOUT_SEC) -> bool:
    watch = ["OneDrive.exe", "OneDrive.Sync.Service.exe"]

    if _is_any_process_running(watch):
        print("[sync] OneDrive ja esta em execucao.")
        return True

    onedrive_exe = _find_onedrive_exe()
    if onedrive_exe is None:
        print("[sync] aviso: OneDrive.exe nao encontrado neste computador.")
        return False

    try:
        subprocess.Popen(
            [str(onedrive_exe)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception as e:
        print(f"[sync] aviso: falha ao iniciar OneDrive: {e}")
        return False

    deadline = time.time() + max(1, timeout_sec)
    while time.time() < deadline:
        if _is_any_process_running(watch):
            print("[sync] OneDrive iniciado com sucesso.")
            return True
        time.sleep(1.0)

    print("[sync] aviso: OneDrive nao confirmou inicializacao a tempo.")
    return False


def wait_file_stable(file_path: Path, timeout_sec: int = UPLOAD_SYNC_WAIT_SEC, poll_sec: float = 2.0) -> bool:
    deadline = time.time() + max(1, timeout_sec)
    prev_sig = None
    stable_hits = 0

    while time.time() < deadline:
        if file_path.exists():
            try:
                st = file_path.stat()
                sig = (st.st_size, st.st_mtime_ns)

                with file_path.open("rb") as f:
                    _ = f.read(1)

                if sig == prev_sig:
                    stable_hits += 1
                    if stable_hits >= 2:
                        return True
                else:
                    stable_hits = 0
                    prev_sig = sig
            except Exception:
                stable_hits = 0

        time.sleep(poll_sec)

    return file_path.exists()


def formatar_transit_time(value):
    """Padroniza transit time numerico para '<n> days' sem mexer em textos ja descritivos."""
    if pd.isna(value):
        return pd.NA

    if isinstance(value, str):
        text = " ".join(value.strip().split())
        if not text:
            return pd.NA
        if "day" in text.lower():
            return text

        numeric_candidate = text.replace(",", ".")
        parsed = pd.to_numeric(numeric_candidate, errors="coerce")
        if pd.notna(parsed):
            number = float(parsed)
            if number.is_integer():
                return f"{int(number)} days"
            return f"{number:g} days"
        return text

    parsed = pd.to_numeric(value, errors="coerce")
    if pd.isna(parsed):
        return value

    number = float(parsed)
    if number.is_integer():
        return f"{int(number)} days"
    return f"{number:g} days"


def check_config():
    """Valida se os caminhos basicos existem."""
    print("DEBUG PROJECT_ROOT:", PROJECT_ROOT)
    print("DEBUG CSV_INPUT:", CSV_INPUT)
    print("DEBUG XLSX_OUTPUT:", XLSX_OUTPUT)
    print("DEBUG SYNC_FOLDER:", SYNC_FOLDER)

    if not CSV_INPUT.exists():
        raise FileNotFoundError(f"CSV de entrada nao encontrado: {CSV_INPUT}")

    if not SYNC_FOLDER.exists():
        SYNC_FOLDER.mkdir(parents=True, exist_ok=True)
        print(f"AVISO: pasta de sincronizacao nao existia e foi criada: {SYNC_FOLDER}")


def aplicar_layout_planilha(ws, total_linhas_dados: int):
    """Aplica layout visual da planilha do cliente."""
    # Ajuste automatico de largura para A:F com limites por coluna.
    width_limits = {
        "A": (12, 24),
        "B": (16, 30),
        "C": (22, 30),
        "D": (12, 18),
        "E": (12, 24),
        "F": (10, 16),
    }
    for col in ["A", "B", "C", "D", "E", "F"]:
        max_len = 0
        for row_num in range(1, total_linhas_dados + 2):
            value = ws[f"{col}{row_num}"].value
            text = "" if value is None else str(value)
            max_len = max(max_len, len(text))
        min_width, max_width = width_limits[col]
        ws.column_dimensions[col].width = max(min_width, min(max_len + 2, max_width))
    ws.column_dimensions["G"].width = 120

    ws["G1"] = OBSERVACAO_CLIENTE
    ws["G1"].alignment = Alignment(horizontal="left", vertical="center", wrap_text=False)
    ws["G1"].font = Font(name="Calibri", size=11)

    # Formata a coluna de frete em USD.
    for row_num in range(2, total_linhas_dados + 2):
        ws[f"C{row_num}"].number_format = "#,##0.00"

    # A tabela cobre as colunas A:F e no minimo ate TABLE_LAST_ROW_MIN.
    table_last_row = max(TABLE_LAST_ROW_MIN, total_linhas_dados + 1)
    tabela = Table(displayName="TabelaFretesCliente", ref=f"A1:F{table_last_row}")
    tabela.tableStyleInfo = TableStyleInfo(
        name="TableStyleMedium2",
        showFirstColumn=False,
        showLastColumn=False,
        showRowStripes=True,
        showColumnStripes=False,
    )
    ws.add_table(tabela)


# =========================================
# 2) GERA A PLANILHA PARA O CLIENTE
# =========================================

def gerar_planilha_cliente():
    print("Lendo CSV interno...")
    if not CSV_INPUT.exists():
        raise FileNotFoundError(f"CSV de entrada nao encontrado: {CSV_INPUT}")

    # Le o CSV usando ; como separador e , como decimal.
    df = pd.read_csv(
        CSV_INPUT,
        sep=";",
        decimal=",",
        thousands=".",
    )

    # Novas colunas relacionadas ao vencedor (vindas do quote_comparison.py):
    # - transit_time
    # - free_time
    wanted_cols = [
        "ORIGEM",
        "PORTO DE DESTINO",
        "best_price",
        "best_carrier",
        "transit_time",
        "free_time",
    ]
    missing = [c for c in wanted_cols if c not in df.columns]
    for col in missing:
        df[col] = pd.NA
        print(f"AVISO: coluna ausente no CSV, preenchendo vazio: {col}")

    # Mantem apenas as colunas desejadas.
    df_cliente = df[wanted_cols].copy()

    # best_price ja vem como numero por causa do decimal=","
    df_cliente["best_price"] = df_cliente["best_price"] + 100
    df_cliente["transit_time"] = df_cliente["transit_time"].map(formatar_transit_time)

    # Nomes finais do layout cliente.
    df_cliente = df_cliente.rename(
        columns={
            "ORIGEM": "Origem",
            "PORTO DE DESTINO": "Porto de Destino",
            "best_price": "Frete para 20'Dry (USD)",
            "best_carrier": "Armador",
            "transit_time": "Transit Time",
            "free_time": "Free Time",
        }
    )

    XLSX_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(XLSX_OUTPUT, engine="openpyxl") as writer:
        df_cliente.to_excel(writer, index=False, sheet_name="Fretes")
        ws = writer.sheets["Fretes"]
        aplicar_layout_planilha(ws, total_linhas_dados=len(df_cliente))

    print(f"Planilha do cliente gerada em: {XLSX_OUTPUT}")


# =========================================
# 3) COPIA PARA A PASTA SINCRONIZADA
# =========================================

def copiar_para_pasta_sincronizada():
    if not XLSX_OUTPUT.exists():
        raise FileNotFoundError(f"Arquivo XLSX nao encontrado: {XLSX_OUTPUT}")

    SYNC_FOLDER.mkdir(parents=True, exist_ok=True)

    if UPLOAD_ENSURE_ONEDRIVE:
        ensure_onedrive_running()

    destino = SYNC_FOLDER / XLSX_OUTPUT.name
    print(f"Copiando arquivo para pasta sincronizada: {destino}")

    shutil.copy2(XLSX_OUTPUT, destino)
    try:
        os.utime(destino, None)
    except Exception:
        pass

    if UPLOAD_SYNC_WAIT_SEC > 0:
        if wait_file_stable(destino):
            print(f"[sync] arquivo estabilizado para sincronizacao: {destino}")
        else:
            print(f"[sync] aviso: nao confirmei estabilidade do arquivo no tempo limite: {destino}")

    print("Copia concluida com sucesso.")
    print("OneDrive/SharePoint foi acionado para sincronizar esse arquivo.")


# =========================================
# 4) MAIN
# =========================================

if __name__ == "__main__":
    check_config()
    gerar_planilha_cliente()
    copiar_para_pasta_sincronizada()
