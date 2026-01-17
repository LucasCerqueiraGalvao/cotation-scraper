import math
from pathlib import Path

import pandas as pd

# ----------------------------------------------------------------------
# Caminhos
# ----------------------------------------------------------------------
ROOT = Path(r"C:\Users\lucas\Documents\Projects\professional\Cotation Scrapers")

# Breakdowns
CMA_BREAKDOWNS    = ROOT / r"artifacts\output\cma_breakdowns.csv"
HAPAG_BREAKDOWNS  = ROOT / r"artifacts\output\hapag_breakdowns.csv"
MAERSK_BREAKDOWNS = ROOT / r"artifacts\output\maersk_breakdowns.csv"

# Jobs
CMA_JOBS    = ROOT / r"artifacts\input\cma_jobs.xlsx"
HAPAG_JOBS  = ROOT / r"artifacts\input\hapag_jobs.xlsx"
MAERSK_JOBS = ROOT / r"artifacts\input\maersk_jobs.xlsx"

# Flags por rota
DESTINATION_CHARGES_FILE = ROOT / r"artifacts\input\destination_charges.xlsx"
DEST_FLAG_COL_IN_FILE = "DESTINATION CHARGES"     # vazio ou 1
DEST_FLAG_COL_INTERNAL = "use_destination_charges"

USA_FLAG_COL_IN_FILE = "USA"                      # vazio ou 1
USA_FLAG_COL_INTERNAL = "use_usa_import"

# Saída
OUTPUT_FILE = ROOT / r"artifacts\output\comparacao_carriers.csv"


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


# CMA: no seu CSV atual só tem total_all_in
CMA_MAP = {
    "ocean_freight": ["valores"],
    "export_surcharges": ["total_all_in"],
    "freight_surcharges": ["total_all_in"],
    "import_surcharges": ["total_all_in"],
}

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
        "USD Emission Surcharge for SPOT Bookings"
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
# 2) Ler breakdowns + jobs por carrier e trazer o indexador
# ----------------------------------------------------------------------

# --- CMA ---
cma_df = pd.read_csv(CMA_BREAKDOWNS)
cma_jobs = pd.read_excel(CMA_JOBS)
if "indexador" in cma_jobs.columns:
    cma_jobs["indexador"] = normalize_indexador_series(cma_jobs["indexador"])

cma_jobs2 = cma_jobs.rename(columns={"ORIGEM": "ORIGEM_CODE", "PORTO DE DESTINO": "DEST_CODE"})

cma_merged = cma_df.merge(
    cma_jobs2,
    left_on=["origin", "destination"],
    right_on=["ORIGEM_CODE", "DEST_CODE"],
    how="left",
)

if "indexador" in cma_merged.columns:
    cma_merged["indexador"] = normalize_indexador_series(cma_merged["indexador"])

cma_merged = cma_merged.merge(dest_flags, on="indexador", how="left")
for col in [DEST_FLAG_COL_INTERNAL, USA_FLAG_COL_INTERNAL]:
    cma_merged[col] = (
        pd.to_numeric(cma_merged[col], errors="coerce")
        .fillna(0)
        .astype(int)
        .clip(0, 1)
    )

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
hapag_group = hapag_merged.groupby("indexador", as_index=False)["hapag"].max()

# CMA: sem extra específico (USA não muda nada na prática pois total_all_in já está no base)
cma_merged["cma"] = compute_carrier_total(
    cma_merged,
    CMA_MAP,
    dest_flag_col=DEST_FLAG_COL_INTERNAL,
    dest_extra_cols=None,
    usa_flag_col=USA_FLAG_COL_INTERNAL,
)
invalidate_old_quotes(cma_merged, "cma")
cma_group = cma_merged.groupby("indexador", as_index=False)["cma"].max()

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
maersk_group = maersk_merged.groupby("indexador", as_index=False)["maersk"].max()

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
