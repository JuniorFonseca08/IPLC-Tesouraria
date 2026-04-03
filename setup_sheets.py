"""
Script de configuração inicial do Google Sheets.
Cria as abas necessárias e insere os cabeçalhos.
Uso: python setup_sheets.py
"""
import os
from dotenv import load_dotenv
load_dotenv()

from sheets import SheetsDB, TAB_ENTRADAS, TAB_FIXAS, TAB_VARIAVEIS, HEADERS

def setup():
    print("🔧 Configurando Google Sheets...")
    db = SheetsDB()

    for tab in [TAB_ENTRADAS, TAB_FIXAS, TAB_VARIAVEIS]:
        ws = db._get_sheet(tab)
        print(f"  ✅ Aba '{tab}' pronta — cabeçalho: {HEADERS[tab]}")

    ss = db._get_spreadsheet()
    print(f"\n✅ Planilha configurada: {ss.title}")
    print(f"   URL: https://docs.google.com/spreadsheets/d/{ss.id}/edit\n")
    print("🎉 Tudo pronto! Você pode iniciar o servidor com: flask run")

if __name__ == '__main__':
    setup()
