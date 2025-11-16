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
# 3) Calcular total (Ocean + Freight + Import) para cada carrier
# ----------------------------------------------------------------------

# ----------------- HAPAG -----------------
# Colunas no hapag_breakdowns:
#   "Ocean Freight", "Freight Surcharges", "Export Surcharges", "Import Surcharges"
hapag_merged["hapag"] = sum_cols(
    hapag_merged,
    ["Ocean Freight", "Freight Surcharges", "Import Surcharges"],
)

# se tiver várias linhas por indexador (várias tentativas), pega o MAIOR valor
# (última cotação com valor normalmente)
hapag_group = (
    hapag_merged.groupby("indexador", as_index=False)["hapag"].max()
)


# ----------------- CMA -----------------
# Seu cma_breakdowns atual só tem:
#   "total_all_in", "total_currency"
# Aqui vamos usar total_all_in como aproximação de
# Ocean + Freight Surcharges + Import Surcharges.
cma_merged["cma"] = sum_cols(cma_merged, ["total_all_in"])

cma_group = (
    cma_merged.groupby("indexador", as_index=False)["cma"].max()
)


# ----------------- MAERSK -----------------
# Colunas UNK da Maersk com o mapeamento para:
# Ocean Freight, Freight Surcharges, Import Surcharges
MAERSK_OCEAN = [
    "UNK Basic Ocean Freight",
]

MAERSK_FREIGHT_SURCH = [
    "UNK Container Protect Unlimited",
    "UNK Container Protect Essential",
    "UNK Emission Surcharge for SPOT Bookings",
]

MAERSK_IMPORT_SURCH = [
    "UNK Inland Haulage Import",
    "UNK Documentation fee - Destination",
    "UNK Import Service",
    "UNK Terminal Handling Service - Destination",
    "UNK Import Intermodal Fuel Fee",
    "UNK Port Additionals / Port Dues Import",
]

maersk_merged["maersk"] = (
    sum_cols(maersk_merged, MAERSK_OCEAN)
    + sum_cols(maersk_merged, MAERSK_FREIGHT_SURCH)
    + sum_cols(maersk_merged, MAERSK_IMPORT_SURCH)
)

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
