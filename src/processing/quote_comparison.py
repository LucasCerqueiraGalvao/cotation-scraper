import math
import os
import subprocess
import time
import unicodedata
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

# ----------------------------------------------------------------------
# Caminhos
# ----------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env", override=False)


def resolve_env_path(env_name: str, default_path: Path) -> Path:
    raw = os.getenv(env_name)
    if not raw:
        return default_path

    candidate = Path(raw).expanduser()
    if not candidate.is_absolute():
        candidate = PROJECT_ROOT / candidate
    return candidate

# Breakdowns
HAPAG_BREAKDOWNS  = PROJECT_ROOT / "artifacts" / "output" / "hapag_breakdowns.csv"
MAERSK_BREAKDOWNS = PROJECT_ROOT / "artifacts" / "output" / "maersk_breakdowns.csv"

# Jobs
HAPAG_JOBS  = PROJECT_ROOT / "artifacts" / "input" / "hapag_jobs.xlsx"
MAERSK_JOBS = PROJECT_ROOT / "artifacts" / "input" / "maersk_jobs.xlsx"

# CMA cotations (fonte final de preco)
CMA_COTATIONS_FILE = resolve_env_path(
    "CMA_COTATIONS_FILE",
    PROJECT_ROOT / "artifacts" / "input" / "cma_cotations.xlsx",
)
CMA_REQUIRED_COLUMNS = {
    "INDEXADOR",
    "ORIGEM",
    "PORTO DE DESTINO",
    "PRECO FINAL (USD)",
}
CMA_TRANSIT_COL_CANDIDATES = (
    "TRANSIT TIME",
    "TEMPO DE TRANSPORTE",
)
CMA_FREE_TIME_COL_CANDIDATES = ("FREE TIME",)

# Flags por rota
DESTINATION_CHARGES_FILE = PROJECT_ROOT / "artifacts" / "input" / "destination_charges.xlsx"
DEST_FLAG_COL_IN_FILE = "DESTINATION CHARGES"     # vazio ou 1
DEST_FLAG_COL_INTERNAL = "use_destination_charges"

USA_FLAG_COL_IN_FILE = "USA"                      # vazio ou 1
USA_FLAG_COL_INTERNAL = "use_usa_import"

# Saída
OUTPUT_FILE = PROJECT_ROOT / "artifacts" / "output" / "comparacao_carriers.csv"


# ----------------------------------------------------------------------
# CONFIGURAÇÃO: quais categorias entram no total BASE?
# ----------------------------------------------------------------------
# Import fica False porque:
# - Se USA=1 -> soma TODOS imports
# - Se DESTINATION CHARGES=1 e USA!=1 -> soma SÓ itens específicos
CATEGORY_FLAGS = {
    "ocean_freight": True,
    "export_surcharges": False,
    "freight_surcharges": True,
    "import_surcharges": False,
}

# ----------------------------------------------------------------------
# FILTRO DE "COTAÇÃO ANTIGA" (quotedAt / quoted_at)
# ----------------------------------------------------------------------
TIMEZONE = "America/Sao_Paulo"
MAX_QUOTE_AGE_DAYS = 2  # se quoted_at for mais antigo que isso -> vira NaN (como vazio)
SYNC_BEFORE_CMA_READ = os.getenv("SYNC_BEFORE_CMA_READ", "1") != "0"
SYNC_WAIT_TIMEOUT_SEC = int(os.getenv("SYNC_WAIT_TIMEOUT_SEC", "60"))
SYNC_START_TIMEOUT_SEC = int(os.getenv("SYNC_START_TIMEOUT_SEC", "20"))


# ----------------------------------------------------------------------
# MAPEAMENTO DE COLUNAS POR CARRIER
# ----------------------------------------------------------------------
def build_hapag_map_from_columns(columns) -> dict:
    """
    Monta o mapeamento da Hapag automaticamente por prefixo.

    OBS: ignora "Ocean Freight" (seco) pra não duplicar com
    "Freight Charges | Ocean Freight | 20STD".
    """
    cols = [str(c) for c in columns]

    hapag_map = {
        "ocean_freight": [],
        "export_surcharges": [],
        "freight_surcharges": [],
        "import_surcharges": [],
    }

    for c in cols:
        c_strip = c.strip()

        # ignora total estimado (pra não duplicar soma)
        if c_strip.startswith("Estimated Total |"):
            continue

        # ignora Ocean Freight "seco" (duplicaria)
        if c_strip == "Ocean Freight":
            continue

        # export
        if c_strip.startswith("Export Surcharges |") and c_strip.endswith("| 20STD"):
            hapag_map["export_surcharges"].append(c)
            continue

        # freight surcharges
        if c_strip.startswith("Freight Surcharges |") and c_strip.endswith("| 20STD"):
            hapag_map["freight_surcharges"].append(c)
            continue

        # import
        if c_strip.startswith("Import Surcharges |") and c_strip.endswith("| 20STD"):
            hapag_map["import_surcharges"].append(c)
            continue

        # ocean freight detalhado
        if c_strip.startswith("Freight Charges | Ocean Freight |") and c_strip.endswith("| 20STD"):
            hapag_map["ocean_freight"].append(c)
            continue

    # remover duplicatas preservando ordem
    for k in hapag_map:
        hapag_map[k] = list(dict.fromkeys(hapag_map[k]))

    return hapag_map


# MAERSK
MAERSK_MAP = {
    "ocean_freight": [
        "USD Basic Ocean Freight",
    ],
    "export_surcharges": [
        "USD Documentation Fee Origin",
        "USD Terminal Handling Service - Origin",
        "USD Export Service",
    ],
    "freight_surcharges": [
        "USD Emission Surcharge for SPOT Bookings",
        "USD Operational Cost Imports",
        "USD Emergency Risk Surcharge",
        "USD Emission Surcharge for SPOT Bookings",
        "USD Peak Season Surcharge",
    ],
    "import_surcharges": [
        "USD Container Protect Unlimited",
        "USD Container Protect Essential",
        "USD Inland Haulage Import",
        "USD Documentation fee - Destination",
        "USD Import Service",
        "USD Terminal Handling Service - Destination",
        "USD Import Intermodal Fuel Fee",
        "USD Port Additionals / Port Dues Import",
        "COP Inland Haulage Import",
        "USD Inspection Fee- Import",
    ],
}


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------
def normalize_indexador_series(s: pd.Series) -> pd.Series:
    def _norm(x):
        if pd.isna(x):
            return pd.NA
        if isinstance(x, float) and x.is_integer():
            return str(int(x))
        return str(x).strip()

    return s.map(_norm)


def normalize_header_name(name: str) -> str:
    no_accents = "".join(
        ch for ch in unicodedata.normalize("NFKD", str(name))
        if not unicodedata.combining(ch)
    )
    return " ".join(no_accents.upper().strip().split())


def _is_any_process_running(process_names: list[str]) -> bool:
    try:
        out = subprocess.check_output(
            ["tasklist", "/FO", "CSV", "/NH"],
            text=True,
            encoding="utf-8",
            errors="ignore",
        )
    except Exception:
        return False

    out_low = out.lower()
    return any(name.lower() in out_low for name in process_names)


def _find_google_drive_exe() -> Path | None:
    candidates = []
    pf = Path(os.environ.get("ProgramFiles", ""))
    pf86 = Path(os.environ.get("ProgramFiles(x86)", ""))
    local = Path(os.environ.get("LOCALAPPDATA", ""))

    candidates.extend(
        [
            pf / "Google" / "Drive File Stream" / "GoogleDriveFS.exe",
            pf86 / "Google" / "Drive File Stream" / "GoogleDriveFS.exe",
            local / "Google" / "DriveFS" / "GoogleDriveFS.exe",
        ]
    )

    drivefs_root = local / "Google" / "DriveFS"
    if drivefs_root.exists():
        candidates.extend(sorted(drivefs_root.glob("**/GoogleDriveFS.exe"), reverse=True))

    for c in candidates:
        if c.exists():
            return c
    return None


def _find_onedrive_exe() -> Path | None:
    candidates = [
        Path(os.environ.get("ProgramFiles", "")) / "Microsoft OneDrive" / "OneDrive.exe",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "OneDrive" / "OneDrive.exe",
    ]
    for c in candidates:
        if c.exists():
            return c
    return None


def ensure_cloud_sync_running(start_timeout_sec: int = SYNC_START_TIMEOUT_SEC) -> str | None:
    google_proc = ["GoogleDriveFS.exe", "GoogleDriveFS"]
    onedrive_proc = ["OneDrive.exe", "OneDrive.Sync.Service.exe", "OneDrive"]

    if _is_any_process_running(google_proc):
        return "google_drive"
    if _is_any_process_running(onedrive_proc):
        return "onedrive"

    starter = None
    provider = None

    gexe = _find_google_drive_exe()
    if gexe is not None:
        starter = gexe
        provider = "google_drive"
    else:
        oexe = _find_onedrive_exe()
        if oexe is not None:
            starter = oexe
            provider = "onedrive"

    if starter is None or provider is None:
        return None

    try:
        subprocess.Popen([str(starter)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        return None

    deadline = time.time() + max(1, start_timeout_sec)
    watch = google_proc if provider == "google_drive" else onedrive_proc
    while time.time() < deadline:
        if _is_any_process_running(watch):
            return provider
        time.sleep(1.0)

    return None


def wait_file_stable(file_path: Path, timeout_sec: int = SYNC_WAIT_TIMEOUT_SEC, poll_sec: float = 2.0) -> bool:
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


def ensure_cma_file_synced(file_path: Path) -> None:
    if not SYNC_BEFORE_CMA_READ:
        return

    provider = ensure_cloud_sync_running()
    if provider:
        print(f"[sync] sincronizador detectado/iniciado: {provider}.")
    else:
        print("[sync] aviso: nao foi possivel detectar/iniciar Google Drive/OneDrive.")

    ok = wait_file_stable(file_path)
    if ok:
        print(f"[sync] arquivo pronto para leitura: {file_path}")
    else:
        print(f"[sync] aviso: nao consegui confirmar sincronizacao completa: {file_path}")


def load_cma_prices(file_path: Path) -> pd.DataFrame:
    ensure_cma_file_synced(file_path)

    if not file_path.exists():
        raise FileNotFoundError(f"Arquivo da CMA nao encontrado: {file_path}")

    cma_df = pd.read_excel(file_path)
    colmap = {}
    for col in cma_df.columns:
        normalized = normalize_header_name(col)
        if normalized not in colmap:
            colmap[normalized] = col

    missing = CMA_REQUIRED_COLUMNS - set(colmap)
    if missing:
        raise ValueError(
            f"A planilha {file_path} precisa conter as colunas: {sorted(CMA_REQUIRED_COLUMNS)}. "
            f"Faltando: {sorted(missing)}"
        )

    cma_price_src = colmap["PRECO FINAL (USD)"]
    rename_map = {
        colmap["INDEXADOR"]: "indexador",
        cma_price_src: "cma",
    }
    select_cols = ["indexador", "cma"]

    cma_transit_src = next(
        (colmap[c] for c in CMA_TRANSIT_COL_CANDIDATES if c in colmap),
        None,
    )
    if cma_transit_src:
        rename_map[cma_transit_src] = "cma_transit_time"
        select_cols.append("cma_transit_time")

    cma_free_time_src = next(
        (colmap[c] for c in CMA_FREE_TIME_COL_CANDIDATES if c in colmap),
        None,
    )
    if cma_free_time_src:
        rename_map[cma_free_time_src] = "cma_free_time"
        select_cols.append("cma_free_time")

    cma_prices = cma_df.rename(columns=rename_map)[select_cols].copy()

    cma_prices["indexador"] = normalize_indexador_series(cma_prices["indexador"])
    cma_prices["cma"] = pd.to_numeric(cma_prices["cma"], errors="coerce")
    cma_prices = cma_prices.dropna(subset=["indexador"])

    if "cma_transit_time" not in cma_prices.columns:
        cma_prices["cma_transit_time"] = pd.NA
    if "cma_free_time" not in cma_prices.columns:
        cma_prices["cma_free_time"] = pd.NA

    return cma_prices


def sum_cols(df: pd.DataFrame, cols):
    cols = [c for c in cols if c in df.columns]
    if not cols:
        return pd.Series(0, index=df.index)
    return (
        df[cols]
        .apply(pd.to_numeric, errors="coerce")
        .fillna(0)
        .sum(axis=1)
    )


def first_non_empty(series: pd.Series):
    for val in series:
        if pd.isna(val):
            continue
        if str(val).strip() == "":
            continue
        return val
    return pd.NA


def best_price_and_carrier(row):
    valores = {
        "hapag": row.get("hapag", math.nan),
        "cma": row.get("cma", math.nan),
        "maersk": row.get("maersk", math.nan),
    }
    valores_validos = {
        k: v
        for k, v in valores.items()
        if isinstance(v, (int, float)) and not math.isnan(v) and v > 0
    }

    if not valores_validos:
        return pd.Series({"best_price": math.nan, "best_carrier": None})

    best_carrier = min(valores_validos, key=valores_validos.get)
    best_price = valores_validos[best_carrier]
    return pd.Series({"best_price": best_price, "best_carrier": best_carrier})


def winner_transit_time(row):
    carrier = row.get("best_carrier")
    if carrier == "hapag":
        return row.get("hapag_transit_time")
    if carrier == "maersk":
        return row.get("maersk_transit_time")
    if carrier == "cma":
        return row.get("cma_transit_time")
    return pd.NA


def winner_free_time(row):
    carrier = row.get("best_carrier")
    if carrier == "hapag":
        return 10
    if carrier == "maersk":
        return 14
    if carrier == "cma":
        return row.get("cma_free_time")
    return pd.NA


def normalize_free_time_value(value):
    """
    Normaliza free_time para evitar saida com sufixo '.0' no CSV.
    Ex.: 14.0 -> 14 (int), mantendo textos descritivos inalterados.
    """
    if pd.isna(value):
        return pd.NA

    if isinstance(value, str):
        text = value.strip()
        if not text:
            return pd.NA
        parsed = pd.to_numeric(text.replace(",", "."), errors="coerce")
        if pd.notna(parsed):
            number = float(parsed)
            if number.is_integer():
                return int(number)
            return float(number)
        return text

    parsed = pd.to_numeric(value, errors="coerce")
    if pd.isna(parsed):
        return value

    number = float(parsed)
    if number.is_integer():
        return int(number)
    return float(number)


def compute_carrier_total(
    df: pd.DataFrame,
    mapping: dict,
    dest_flag_col: str | None = None,
    dest_extra_cols: list[str] | None = None,
    usa_flag_col: str | None = None,
) -> pd.Series:
    """
    TOTAL BASE: soma categorias ativadas em CATEGORY_FLAGS.

    Regras por rota:
      - Se USA=1: soma TODO import_surcharges (todas as colunas mapeadas em import),
        exceto as que já entraram no base.
      - Se DESTINATION CHARGES=1 e USA!=1: soma SÓ dest_extra_cols (itens específicos).

    REGRA NOVA (THC USD-only):
      - Para a HAPAG: qualquer coluna de THC (Terminal Handling...) dentro de Import Surcharges
        só entra na soma se a coluna correspondente "<valor> | Curr" for "USD".
      - Isso vale tanto no caso USA=1 (imports) quanto no caso DESTINATION CHARGES=1 (extras).
      - Para Maersk, como o THC está no nome da coluna (ex.: "USD Terminal Handling Service - Destination"),
        você controla isso escolhendo apenas a coluna USD no MAERSK_DEST_EXTRA (como já está).
    """

    # ---------------------------
    # Helpers internos (sem depender de imports no topo)
    # ---------------------------
    import re

    def _clean_curr(x) -> str:
        """Extrai código de moeda (USD/EUR/BRL...) de uma célula qualquer."""
        if x is None or pd.isna(x):
            return ""
        s = str(x).strip().upper()
        m = re.search(r"([A-Z]{3})", s)
        return m.group(1) if m else ""

    def _is_hapag_thc_col(colname: str) -> bool:
        """
        Detecta colunas de THC no PADRÃO HAPAG (pipes):
          "Import Surcharges | Terminal Handling Charge ... | 20STD"
        Você pode deixar mais/menos estrito se quiser.
        """
        c = str(colname).strip()
        return (
            c.startswith("Import Surcharges |")
            and "Terminal Handling" in c
            and c.endswith("| 20STD")
        )

    def sum_cols_usd_only_for_thc(df_: pd.DataFrame, cols_: list[str]) -> pd.Series:
        """
        Soma colunas numéricas, mas para colunas de THC (padrão Hapag),
        só soma quando a coluna "<col> | Curr" for USD.

        - Para colunas NÃO-THC: soma normal (como antes).
        - Para colunas THC Hapag:
            - se não existir a coluna de moeda -> NÃO soma (fica 0)
            - se Curr != USD -> NÃO soma (fica 0)
        """
        out = pd.Series(0.0, index=df_.index)

        for col in cols_:
            if col not in df_.columns:
                continue

            vals = pd.to_numeric(df_[col], errors="coerce").fillna(0)

            # Se NÃO for THC no padrão Hapag, soma normal
            if not _is_hapag_thc_col(col):
                out = out + vals
                continue

            # Se for THC Hapag, exige Curr == USD
            curr_col = f"{col} | Curr"
            if curr_col not in df_.columns:
                # sem informação de moeda -> não soma
                continue

            currs = df_[curr_col].map(_clean_curr)
            vals_usd_only = vals.where(currs == "USD", 0)
            out = out + vals_usd_only

        return out

    # ---------------------------
    # 1) total base (categorias ativadas)
    # ---------------------------
    cols_to_sum = set()
    for cat, cols in mapping.items():
        if CATEGORY_FLAGS.get(cat, False):
            cols_to_sum.update(cols)

    # base: soma padrão (não mexe aqui)
    total = sum_cols(df, list(cols_to_sum))

    # ---------------------------
    # flags
    # ---------------------------
    flag_dest = None
    if dest_flag_col and dest_flag_col in df.columns:
        flag_dest = (
            pd.to_numeric(df[dest_flag_col], errors="coerce")
            .fillna(0)
            .astype(int)
            .clip(0, 1)
        )

    flag_usa = None
    if usa_flag_col and usa_flag_col in df.columns:
        flag_usa = (
            pd.to_numeric(df[usa_flag_col], errors="coerce")
            .fillna(0)
            .astype(int)
            .clip(0, 1)
        )

    # ---------------------------
    # 2) USA -> soma TODOS imports (com regra nova de THC USD-only pra Hapag)
    # ---------------------------
    if flag_usa is not None:
        import_cols = [
            c for c in mapping.get("import_surcharges", [])
            if c in df.columns and c not in cols_to_sum
        ]
        if import_cols:
            # Aqui aplicamos a regra:
            # - colunas THC Hapag só entram se Curr == USD
            # - resto soma normal
            import_total = sum_cols_usd_only_for_thc(df, import_cols)
            total = total + (import_total * flag_usa)

    # ---------------------------
    # 3) DESTINATION CHARGES -> soma só itens específicos (somente se USA!=1)
    #     (também com regra nova THC USD-only pra Hapag)
    # ---------------------------
    if flag_dest is not None and dest_extra_cols:
        extra_cols = [
            c for c in dest_extra_cols
            if c in df.columns and c not in cols_to_sum
        ]
        if extra_cols:
            # Aplica mesma regra:
            # - THC Hapag só soma se Curr == USD
            extra_total = sum_cols_usd_only_for_thc(df, extra_cols)

            if flag_usa is not None:
                apply_mask = (flag_dest == 1) & (flag_usa != 1)
                total = total + extra_total.where(apply_mask, 0)
            else:
                total = total + (extra_total * flag_dest)

    return total

def invalidate_old_quotes(df: pd.DataFrame, value_col: str, max_age_days: int = MAX_QUOTE_AGE_DAYS) -> None:
    possible_cols = ["quotedAt", "quoted_at", "quotedAtUtc", "quoted_at_utc", "quoted_date", "quotedDate"]
    qcol = next((c for c in possible_cols if c in df.columns), None)
    if not qcol:
        return

    quoted = pd.to_datetime(df[qcol], errors="coerce")

    # timezone handling
    try:
        tzinfo = quoted.dt.tz
    except Exception:
        tzinfo = None

    if tzinfo is not None:
        quoted = quoted.dt.tz_convert(TIMEZONE)
    else:
        quoted = quoted.dt.tz_localize(TIMEZONE, ambiguous="NaT", nonexistent="NaT")

    cutoff = pd.Timestamp.now(tz=TIMEZONE) - pd.Timedelta(days=max_age_days)

    df.loc[quoted < cutoff, value_col] = math.nan


# ----------------------------------------------------------------------
# 1) Ler jobs e criar base canônica de rotas (usando MAERSK)
# ----------------------------------------------------------------------
maersk_jobs = pd.read_excel(MAERSK_JOBS)
if "indexador" in maersk_jobs.columns:
    maersk_jobs["indexador"] = normalize_indexador_series(maersk_jobs["indexador"])

routes_base = maersk_jobs[["indexador", "ORIGEM", "PORTO DE DESTINO"]].drop_duplicates()

# ----------------------------------------------------------------------
# 1.1) Ler flags (destination charges + USA) e anexar na base
# ----------------------------------------------------------------------
dest_df = pd.read_excel(DESTINATION_CHARGES_FILE)

required = {"indexador", DEST_FLAG_COL_IN_FILE, USA_FLAG_COL_IN_FILE}
missing = required - set(dest_df.columns)
if missing:
    raise ValueError(
        f"O arquivo {DESTINATION_CHARGES_FILE} precisa ter as colunas: {required}. "
        f"Faltando: {missing}"
    )

dest_df = dest_df[["indexador", DEST_FLAG_COL_IN_FILE, USA_FLAG_COL_IN_FILE]].copy()
dest_df["indexador"] = normalize_indexador_series(dest_df["indexador"])

dest_df[DEST_FLAG_COL_INTERNAL] = (
    pd.to_numeric(dest_df[DEST_FLAG_COL_IN_FILE], errors="coerce")
    .fillna(0)
    .astype(int)
    .clip(0, 1)
)

dest_df[USA_FLAG_COL_INTERNAL] = (
    pd.to_numeric(dest_df[USA_FLAG_COL_IN_FILE], errors="coerce")
    .fillna(0)
    .astype(int)
    .clip(0, 1)
)

dest_flags = (
    dest_df.groupby("indexador", as_index=False)[[DEST_FLAG_COL_INTERNAL, USA_FLAG_COL_INTERNAL]]
    .max()
)

routes_base = routes_base.merge(dest_flags, on="indexador", how="left")
for col in [DEST_FLAG_COL_INTERNAL, USA_FLAG_COL_INTERNAL]:
    routes_base[col] = (
        pd.to_numeric(routes_base[col], errors="coerce")
        .fillna(0)
        .astype(int)
        .clip(0, 1)
    )

# ----------------------------------------------------------------------
# 2) Ler dados por carrier e trazer o indexador
# ----------------------------------------------------------------------

# --- CMA (preco final direto da planilha dedicada) ---
cma_prices = load_cma_prices(CMA_COTATIONS_FILE)

# --- HAPAG ---
hapag_df = pd.read_csv(HAPAG_BREAKDOWNS)

# monta o HAPAG_MAP automaticamente pelas colunas reais do CSV
HAPAG_MAP = build_hapag_map_from_columns(hapag_df.columns)

hapag_jobs = pd.read_excel(HAPAG_JOBS)
if "indexador" in hapag_jobs.columns:
    hapag_jobs["indexador"] = normalize_indexador_series(hapag_jobs["indexador"])

hapag_jobs2 = hapag_jobs.rename(columns={"ORIGEM": "ORIGEM_CODE", "PORTO DE DESTINO": "DEST_CODE"})

hapag_merged = hapag_df.merge(
    hapag_jobs2,
    left_on=["origin", "destination"],
    right_on=["ORIGEM_CODE", "DEST_CODE"],
    how="left",
)

if "indexador" in hapag_merged.columns:
    hapag_merged["indexador"] = normalize_indexador_series(hapag_merged["indexador"])

hapag_merged = hapag_merged.merge(dest_flags, on="indexador", how="left")
for col in [DEST_FLAG_COL_INTERNAL, USA_FLAG_COL_INTERNAL]:
    hapag_merged[col] = (
        pd.to_numeric(hapag_merged[col], errors="coerce")
        .fillna(0)
        .astype(int)
        .clip(0, 1)
    )

# --- MAERSK ---
maersk_df = pd.read_csv(MAERSK_BREAKDOWNS)

maersk_merged = maersk_df.merge(
    maersk_jobs,
    left_on=["origin", "destination"],
    right_on=["ORIGEM", "PORTO DE DESTINO"],
    how="left",
)

if "indexador" in maersk_merged.columns:
    maersk_merged["indexador"] = normalize_indexador_series(maersk_merged["indexador"])

maersk_merged = maersk_merged.merge(dest_flags, on="indexador", how="left")
for col in [DEST_FLAG_COL_INTERNAL, USA_FLAG_COL_INTERNAL]:
    maersk_merged[col] = (
        pd.to_numeric(maersk_merged[col], errors="coerce")
        .fillna(0)
        .astype(int)
        .clip(0, 1)
    )

# ----------------------------------------------------------------------
# 3) Calcular total dinâmico para cada carrier
#    + invalidar cotações antigas
#    + USA=1 soma TODOS imports
#    + destination charges=1 soma só item específico (se USA!=1)
# ----------------------------------------------------------------------

# HAPAG: item específico quando destination charges=1
HAPAG_DEST_EXTRA = ["Import Surcharges | Terminal Handling Charge Dest. | 20STD"]

hapag_merged["hapag"] = compute_carrier_total(
    hapag_merged,
    HAPAG_MAP,
    dest_flag_col=DEST_FLAG_COL_INTERNAL,
    dest_extra_cols=HAPAG_DEST_EXTRA,
    usa_flag_col=USA_FLAG_COL_INTERNAL,
)
invalidate_old_quotes(hapag_merged, "hapag")
if "Estimated Transportation Days" not in hapag_merged.columns:
    hapag_merged["Estimated Transportation Days"] = pd.NA
hapag_group = hapag_merged.groupby("indexador", as_index=False).agg(
    hapag=("hapag", "max"),
    hapag_transit_time=("Estimated Transportation Days", first_non_empty),
)

# CMA: usa diretamente PRECO FINAL (USD) da planilha cma_cotations.xlsx
cma_group = cma_prices.groupby("indexador", as_index=False).agg(
    cma=("cma", "max"),
    cma_transit_time=("cma_transit_time", first_non_empty),
    cma_free_time=("cma_free_time", first_non_empty),
)

# MAERSK: item específico quando destination charges=1
MAERSK_DEST_EXTRA = ["USD Terminal Handling Service - Destination"]

maersk_merged["maersk"] = compute_carrier_total(
    maersk_merged,
    MAERSK_MAP,
    dest_flag_col=DEST_FLAG_COL_INTERNAL,
    dest_extra_cols=MAERSK_DEST_EXTRA,
    usa_flag_col=USA_FLAG_COL_INTERNAL,
)
invalidate_old_quotes(maersk_merged, "maersk")
if "offer_transit_time" not in maersk_merged.columns:
    maersk_merged["offer_transit_time"] = pd.NA
maersk_group = maersk_merged.groupby("indexador", as_index=False).agg(
    maersk=("maersk", "max"),
    maersk_transit_time=("offer_transit_time", first_non_empty),
)

# ----------------------------------------------------------------------
# 4) Juntar tudo pela base canônica (rotas da Maersk)
# ----------------------------------------------------------------------
base = routes_base.copy()  # indexador, ORIGEM, PORTO DE DESTINO, flags

base = base.merge(hapag_group, on="indexador", how="left")
base = base.merge(cma_group, on="indexador", how="left")
base = base.merge(maersk_group, on="indexador", how="left")

for col in ["hapag", "cma", "maersk"]:
    base[col] = pd.to_numeric(base[col], errors="coerce")

# ----------------------------------------------------------------------
# 5) Calcular menor valor (ignorando 0 e vazio) e empresa vencedora
# ----------------------------------------------------------------------
best = base.apply(best_price_and_carrier, axis=1)
base["best_price"] = best["best_price"]
base["best_carrier"] = best["best_carrier"]
base["transit_time"] = base.apply(winner_transit_time, axis=1)
base["free_time"] = base.apply(winner_free_time, axis=1)
base["free_time"] = base["free_time"].map(normalize_free_time_value)

base["key"] = base["ORIGEM"].astype(str) + "-" + base["PORTO DE DESTINO"].astype(str)

# Reordenar colunas (incluí as flags pra auditar)
base = base[
    [
        "key",
        "ORIGEM",
        "PORTO DE DESTINO",
        DEST_FLAG_COL_INTERNAL,
        USA_FLAG_COL_INTERNAL,
        "hapag",
        "cma",
        "maersk",
        "best_price",
        "best_carrier",
        "transit_time",
        "free_time",
        "indexador",
    ]
]

# ----------------------------------------------------------------------
# 6) Salvar CSV final
# ----------------------------------------------------------------------
OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
base.to_csv(
    OUTPUT_FILE,
    index=False,
    encoding="utf-8-sig",
    sep=";",
    decimal=",",
)

print(f"Arquivo gerado em: {OUTPUT_FILE}")

