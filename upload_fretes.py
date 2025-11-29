import os
from pathlib import Path
import shutil

import pandas as pd
from dotenv import load_dotenv

# =========================================
# 1) CONFIGURAÇÕES GERAIS
# =========================================

BASE_DIR = Path(__file__).resolve().parent

# Se ainda quiser usar .env pra outras coisas, mantemos:
load_dotenv(BASE_DIR / ".env", override=True)

# Arquivos locais (onde o seu pipeline já grava o CSV)
CSV_INPUT = BASE_DIR / "artifacts" / "output" / "comparacao_carriers.csv"
XLSX_OUTPUT = BASE_DIR / "artifacts" / "output" / "comparacao_carriers_cliente.xlsx"

# >>> PASTA SINCRONIZADA COM O ONEDRIVE / SHAREPOINT <<<
SYNC_FOLDER = Path(
    r"C:\Users\lucas\excels\Data Analisys Team - Documentos\Ceramic Customer Freight"
)

def check_config():
    """Valida se os caminhos básicos existem."""
    print("DEBUG BASE_DIR:", BASE_DIR)
    print("DEBUG CSV_INPUT:", CSV_INPUT)
    print("DEBUG XLSX_OUTPUT:", XLSX_OUTPUT)
    print("DEBUG SYNC_FOLDER:", SYNC_FOLDER)

    if not CSV_INPUT.exists():
        raise FileNotFoundError(f"CSV de entrada não encontrado: {CSV_INPUT}")

    # A pasta sincronizada precisa existir (você criou no OneDrive).
    if not SYNC_FOLDER.exists():
        raise FileNotFoundError(
            f"Pasta sincronizada não encontrada: {SYNC_FOLDER}\n"
            "Verifique se a sincronização do OneDrive está ativa "
            "e se o caminho está correto."
        )


# =========================================
# 2) GERA A PLANILHA PARA O CLIENTE
# =========================================

def gerar_planilha_cliente():
    print("Lendo CSV interno...")
    if not CSV_INPUT.exists():
        raise FileNotFoundError(f"CSV de entrada não encontrado: {CSV_INPUT}")

    # Lê o CSV usando ; como separador e , como decimal
    df = pd.read_csv(
        CSV_INPUT,
        sep=";",
        decimal=",",       # <--- aqui é o pulo do gato
        thousands="."      # se aparecer algo tipo 1.587,0 também trata
    )

    # Mantém apenas as colunas desejadas
    df_cliente = df[["ORIGEM", "PORTO DE DESTINO", "best_price", "best_carrier"]].copy()

    # best_price já vem como número por causa do decimal=","
    df_cliente["best_price"] = df_cliente["best_price"] + 100

    # Renomeia colunas para ficar bonitinho pro cliente
    df_cliente = df_cliente.rename(
        columns={
            "ORIGEM": "Origem",
            "PORTO DE DESTINO": "Porto de Destino",
            "best_price": "Preço Final (USD)",
            "best_carrier": "Armador Vencedor",
        }
    )

    # Garante que a pasta existe e salva em XLSX
    XLSX_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    df_cliente.to_excel(XLSX_OUTPUT, index=False)

    print(f"Planilha do cliente gerada em: {XLSX_OUTPUT}")

# =========================================
# 3) COPIA PARA A PASTA SINCRONIZADA
# =========================================

def copiar_para_pasta_sincronizada():
    if not XLSX_OUTPUT.exists():
        raise FileNotFoundError(f"Arquivo XLSX não encontrado: {XLSX_OUTPUT}")

    SYNC_FOLDER.mkdir(parents=True, exist_ok=True)

    destino = SYNC_FOLDER / XLSX_OUTPUT.name
    print(f"Copiando arquivo para pasta sincronizada: {destino}")

    # copy2 mantém metadata básica (data modificação etc.)
    shutil.copy2(XLSX_OUTPUT, destino)

    print("✔️ Cópia concluída com sucesso.")
    print("Agora o OneDrive/SharePoint sincroniza esse arquivo automaticamente.")


# =========================================
# 4) MAIN
# =========================================

if __name__ == "__main__":
    check_config()
    gerar_planilha_cliente()
    copiar_para_pasta_sincronizada()
