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

# Saída
OUTPUT_FILE = ROOT / r"artifacts\output\comparacao_carriers.csv"


# ----------------------------------------------------------------------
# CONFIGURAÇÃO: quais categorias entram no total?
# ----------------------------------------------------------------------
# Se estiver True, TODAS as colunas mapeadas naquela categoria
# serão somadas no total do carrier.
CATEGORY_FLAGS = {
    "ocean_freight": True,   # "Ocean Freight"
    "export_surcharges": False,
    "freight_surcharges": True,  # "Freight Surcharges"
    "import_surcharges": False,
}

# ----------------------------------------------------------------------
# MAPEAMENTO DE COLUNAS POR CARRIER
# ----------------------------------------------------------------------

# HAPAG: colunas do hapag_breakdowns.csv
HAPAG_MAP = {
    "ocean_freight": ["Ocean Freight"],
    "export_surcharges": ["Export Surcharges"],
    "freight_surcharges": ["Freight Surcharges"],
    "import_surcharges": ["Import Surcharges"],
}

# CMA: no seu CSV atual só tem total_all_in.
# Aqui, mapeamos total_all_in para todas as categorias,
# mas na hora de somar usamos conjunto de colunas,
# então total_all_in só entra UMA vez mesmo se várias categorias estiverem True.
CMA_MAP = {
    "ocean_freight": ["total_all_in"],
    "export_surcharges": ["total_all_in"],
    "freight_surcharges": ["total_all_in"],
    "import_surcharges": ["total_all_in"],
}

# MAERSK: colunas do maersk_breakdowns.csv
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
        "USD Container Protect Unlimited",
        "USD Container Protect Essential",
        # Se existir essa coluna no CSV, ela entra; se não existir, é ignorada pelo sum_cols
        "USD Emission Surcharge for SPOT Bookings",
    ],
    "import_surcharges": [
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
def sum_cols(df: pd.DataFrame, cols):
    """
    Soma colunas numéricas, ignorando as que não existirem.
    Converte para número e trata NaN como 0.
    """
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
    # Ignora zeros e NaN
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


def compute_carrier_total(df: pd.DataFrame, mapping: dict) -> pd.Series:
    """
    Dado um DataFrame e um mapeamento {categoria: [colunas]},
    aplica CATEGORY_FLAGS para decidir quais categorias entram
    e soma todas as colunas correspondentes (sem duplicar).
    """
    cols_to_sum = set()
    for cat, cols in mapping.items():
        if CATEGORY_FLAGS.get(cat, False):
            cols_to_sum.update(cols)
    return sum_cols(df, list(cols_to_sum))


# ----------------------------------------------------------------------
# 1) Ler jobs e criar base canônica de rotas (usando MAERSK)
# ----------------------------------------------------------------------
maersk_jobs = pd.read_excel(MAERSK_JOBS)

# Base de rotas "bonita" (nomes Maersk) para o usuário
routes_base = maersk_jobs[["indexador", "ORIGEM", "PORTO DE DESTINO"]].drop_duplicates()


# ----------------------------------------------------------------------
# 2) Ler breakdowns + jobs por carrier e trazer o indexador
# ----------------------------------------------------------------------
# --- CMA ---
cma_df = pd.read_csv(CMA_BREAKDOWNS)
cma_jobs = pd.read_excel(CMA_JOBS)

# Renomear para facilitar merge (mantendo ORIGEM/PORTO DE DESTINO originais)
cma_jobs2 = cma_jobs.rename(
    columns={
        "ORIGEM": "ORIGEM_CODE",
        "PORTO DE DESTINO": "DEST_CODE",
    }
)

cma_merged = cma_df.merge(
    cma_jobs2,
    left_on=["origin", "destination"],
    right_on=["ORIGEM_CODE", "DEST_CODE"],
    how="left",
)


# --- HAPAG ---
hapag_df = pd.read_csv(HAPAG_BREAKDOWNS)
hapag_jobs = pd.read_excel(HAPAG_JOBS)

hapag_jobs2 = hapag_jobs.rename(
    columns={
        "ORIGEM": "ORIGEM_CODE",
        "PORTO DE DESTINO": "DEST_CODE",
    }
)

hapag_merged = hapag_df.merge(
    hapag_jobs2,
    left_on=["origin", "destination"],
    right_on=["ORIGEM_CODE", "DEST_CODE"],
    how="left",
)


# --- MAERSK ---
maersk_df = pd.read_csv(MAERSK_BREAKDOWNS)

maersk_merged = maersk_df.merge(
    maersk_jobs,
    left_on=["origin", "destination"],
    right_on=["ORIGEM", "PORTO DE DESTINO"],
    how="left",
)


# ----------------------------------------------------------------------
# 3) Calcular total dinâmico para cada carrier (usando flags + mapping)
# ----------------------------------------------------------------------

# HAPAG
hapag_merged["hapag"] = compute_carrier_total(hapag_merged, HAPAG_MAP)
hapag_group = (
    hapag_merged.groupby("indexador", as_index=False)["hapag"].max()
)

# CMA
cma_merged["cma"] = compute_carrier_total(cma_merged, CMA_MAP)
cma_group = (
    cma_merged.groupby("indexador", as_index=False)["cma"].max()
)

# MAERSK
maersk_merged["maersk"] = compute_carrier_total(maersk_merged, MAERSK_MAP)
maersk_group = (
    maersk_merged.groupby("indexador", as_index=False)["maersk"].max()
)


# ----------------------------------------------------------------------
# 4) Juntar tudo pela base canônica (rotas da Maersk)
# ----------------------------------------------------------------------
base = routes_base.copy()  # indexador, ORIGEM, PORTO DE DESTINO

base = base.merge(hapag_group, on="indexador", how="left")
base = base.merge(cma_group, on="indexador", how="left")
base = base.merge(maersk_group, on="indexador", how="left")

# Garantir numérico
for col in ["hapag", "cma", "maersk"]:
    base[col] = pd.to_numeric(base[col], errors="coerce")


# ----------------------------------------------------------------------
# 5) Calcular menor valor (ignorando 0 e vazio) e empresa vencedora
# ----------------------------------------------------------------------
best = base.apply(best_price_and_carrier, axis=1)
base["best_price"] = best["best_price"]
base["best_carrier"] = best["best_carrier"]

# Coluna key = origin+destination (usando nomes da Maersk)
base["key"] = base["ORIGEM"].astype(str) + "-" + base["PORTO DE DESTINO"].astype(str)

# Reordenar colunas
base = base[
    [
        "key",
        "ORIGEM",              # origin legível (Maersk)
        "PORTO DE DESTINO",    # destination legível (Maersk)
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
    sep=";",        # separador de colunas
    decimal=","     # separador decimal
)

print(f"Arquivo gerado em: {OUTPUT_FILE}")
