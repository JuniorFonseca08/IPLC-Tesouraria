"""
Google Sheets database layer — otimizado para baixo consumo de quota.

Estratégia de cache:
  • Os dados de CADA ABA são carregados em memória em UMA ÚNICA chamada
    (get_all_values), e guardados com TTL.
  • Filtrar por mês é feito em Python — sem chamadas extras à API.
  • Writes invalidam apenas o cache da aba afetada.

Resultado prático:
  • Antes: 1 mês = 3 chamadas; 12 meses (dashboard) = 36 chamadas → 429
  • Depois: 3 chamadas para carregar tudo (1 por aba), reutilizadas por TTL.
"""

import os
import json
import time
import threading
import gspread
from google.oauth2.service_account import Credentials
from dotenv import load_dotenv

load_dotenv()

SCOPES = [
    'https://www.googleapis.com/auth/spreadsheets',
    'https://www.googleapis.com/auth/drive',
]

TAB_ENTRADAS  = 'Entradas'
TAB_FIXAS     = 'Despesas_Fixas'
TAB_VARIAVEIS = 'Despesas_Variaveis'

HEADERS = {
    TAB_ENTRADAS:   ['Mes', 'Data', 'Dizimos', 'Ofertas', 'descricao', 'tipo'],
    TAB_FIXAS:      ['Mes', 'Descricao', 'Valor'],
    TAB_VARIAVEIS:  ['Mes', 'Data', 'Descricao', 'Valor'],
}

CACHE_TTL = 45  # segundos
_lock = threading.Lock()


class SheetsDB:
    def __init__(self):
        self._gc          = None
        self._spreadsheet = None
        self._tab_cache   = {}  # { tab_name: {'data': [...], 'expire': float} }

    # ── Conexão ──────────────────────────────────────────────────────────────

    def _get_client(self):
        if self._gc:
            return self._gc
        creds_json = os.environ.get('GOOGLE_CREDENTIALS_JSON')
        creds_file = os.environ.get('GOOGLE_CREDENTIALS_FILE', 'credentials.json')
        if creds_json:
            creds = Credentials.from_service_account_info(json.loads(creds_json), scopes=SCOPES)
        elif os.path.exists(creds_file):
            creds = Credentials.from_service_account_file(creds_file, scopes=SCOPES)
        else:
            raise RuntimeError(
                "Credenciais Google não encontradas. "
                "Defina GOOGLE_CREDENTIALS_JSON ou coloque credentials.json na raiz."
            )
        self._gc = gspread.authorize(creds)
        return self._gc

    def _get_spreadsheet(self):
        if self._spreadsheet:
            return self._spreadsheet
        gc = self._get_client()
        sid = os.environ.get('SPREADSHEET_ID')
        if sid:
            self._spreadsheet = gc.open_by_key(sid)
        else:
            title = os.environ.get('SPREADSHEET_TITLE', 'Tesouraria Igreja')
            try:
                self._spreadsheet = gc.open(title)
            except gspread.SpreadsheetNotFound:
                self._spreadsheet = gc.create(title)
        return self._spreadsheet

    def _get_ws(self, tab_name):
        ss = self._get_spreadsheet()
        try:
            ws = ss.worksheet(tab_name)
        except gspread.WorksheetNotFound:
            ws = ss.add_worksheet(title=tab_name, rows=2000, cols=10)
            ws.append_row(HEADERS[tab_name])
            return ws
        if not ws.row_values(1):
            ws.append_row(HEADERS[tab_name])
        return ws

    # ── Cache por aba ─────────────────────────────────────────────────────────

    def _load_tab(self, tab_name):
        """
        Carrega TODOS os registros da aba (1 chamada à API), com cache TTL.
        Retorna lista de dicts com chaves em minúsculo + 'row_id'.
        """
        with _lock:
            entry = self._tab_cache.get(tab_name)
            if entry and time.time() < entry['expire']:
                return entry['data']

        ws   = self._get_ws(tab_name)
        hdrs = HEADERS[tab_name]
        raw  = ws.get_all_values()  # 1 única chamada à API por aba

        data = []
        if len(raw) > 1:
            for i, row in enumerate(raw[1:], start=2):
                padded = (row + [''] * len(hdrs))[:len(hdrs)]
                d = {h.lower(): v.strip() for h, v in zip(hdrs, padded)}
                d['row_id'] = str(i)
                data.append(d)

        with _lock:
            self._tab_cache[tab_name] = {'data': data, 'expire': time.time() + CACHE_TTL}

        return data

    def _invalidate(self, tab_name):
        with _lock:
            self._tab_cache.pop(tab_name, None)

    def invalidate_all(self):
        with _lock:
            self._tab_cache.clear()

    # ── Filtros (sem chamadas extras) ─────────────────────────────────────────

    def _for_month(self, tab_name, mes_str):
        return [r for r in self._load_tab(tab_name) if r.get('mes') == mes_str]

    @staticmethod
    def _flt(v):
        try:
            return float(str(v).replace(',', '.').strip() or 0)
        except Exception:
            return 0.0

    # ── ENTRADAS ─────────────────────────────────────────────────────────────

    def delete_entrada(self, row_id):
        ws = self._get_ws(TAB_ENTRADAS)

        ws.update(f'A{row_id}:G{row_id}', [['', '', '0', '0', '0', '', 'deleted']])

        self._invalidate(TAB_ENTRADAS)

    def get_entradas(self, mes_str):
        rows = self._for_month(TAB_ENTRADAS, mes_str)
        for r in rows:
            r['dizimos'] = self._flt(r.get('dizimos'))
            r['ofertas']  = self._flt(r.get('ofertas'))
            r['descricao'] = r.get('descricao', '')
            r['tipo'] = r.get('tipo', 'normal')
        return rows

    def get_all_entradas(self):
        rows = list(self._load_tab(TAB_ENTRADAS))
        for r in rows:
            r['dizimos'] = self._flt(r.get('dizimos'))
            r['ofertas'] = self._flt(r.get('ofertas'))
            r['descricao'] = r.get('descricao', '')
            r['tipo'] = r.get('tipo', 'normal')
        return rows

    def upsert_entradas_batch(self, mes, rows_data):
        ws = self._get_ws(TAB_ENTRADAS)
        changed = False
        result_rows = []

        def normalize_date(date_str):
            """Garante que a data esteja no formato dd/mm/yyyy."""
            if not date_str:
                return ''
            if '/' in date_str:
                return date_str
            if '-' in date_str:
                try:
                    y, m, d = date_str.split('-')
                    return f"{d}/{m}/{y}"
                except Exception:
                    return date_str
            return date_str

        for row in rows_data:
            data = normalize_date(row.get('data'))
            diz  = row.get('dizimos', 0)
            ofe  = row.get('ofertas', 0)
            desc = row.get('descricao', '')
            tipo = row.get('tipo', 'domingo')

            values = [mes, data, str(diz), str(ofe), desc, tipo]

            row_id = row.get('row_id')
            if row_id:
                rid = int(row_id)
                ws.update(f'A{rid}:F{rid}', [values])
                changed = True
                result_rows.append({**row, 'row_id': str(rid)})
            elif diz or ofe or desc:
                ws.append_row(values)
                changed = True
                all_data = ws.get_all_values()
                new_rid = str(len(all_data))
                result_rows.append({**row, 'row_id': new_rid})
            else:
                result_rows.append(row)

        if changed:
            self._invalidate(TAB_ENTRADAS)

        return result_rows
    
    # compatibilidade com rotas existentes
    def insert_entrada(self, mes, data, dizimos, ofertas):
        self._get_ws(TAB_ENTRADAS).append_row([mes, data, str(dizimos or 0), str(ofertas or 0)])
        self._invalidate(TAB_ENTRADAS)

    def update_entrada(self, row_id, mes, data, dizimos, ofertas):
        ws = self._get_ws(TAB_ENTRADAS)
        ws.update(f'A{int(row_id)}:D{int(row_id)}', [[mes, data, str(dizimos or 0), str(ofertas or 0)]])
        self._invalidate(TAB_ENTRADAS)

    # ── DESPESAS FIXAS ────────────────────────────────────────────────────────

    def get_despesas_fixas(self, mes_str):
        rows = self._for_month(TAB_FIXAS, mes_str)
        for r in rows:
            r['valor'] = self._flt(r.get('valor'))
        return rows

    def get_all_despesas_fixas(self):
        rows = list(self._load_tab(TAB_FIXAS))
        for r in rows:
            r['valor'] = self._flt(r.get('valor'))
        return rows

    def upsert_fixas_batch(self, mes, rows_data):
        ws      = self._get_ws(TAB_FIXAS)
        changed = False
        for row in rows_data:
            if not row.get('descricao'):
                continue
            if row.get('row_id'):
                rid = int(row['row_id'])
                ws.update(f'A{rid}:C{rid}', [[mes, row['descricao'], str(row.get('valor', 0))]])
                changed = True
            else:
                ws.append_row([mes, row['descricao'], str(row.get('valor', 0))])
                changed = True
        if changed:
            self._invalidate(TAB_FIXAS)

    def insert_despesa_fixa(self, mes, descricao, valor):
        self._get_ws(TAB_FIXAS).append_row([mes, descricao, str(valor or 0)])
        self._invalidate(TAB_FIXAS)

    def update_despesa_fixa(self, row_id, mes, descricao, valor):
        ws = self._get_ws(TAB_FIXAS)
        ws.update(f'A{int(row_id)}:C{int(row_id)}', [[mes, descricao, str(valor or 0)]])
        self._invalidate(TAB_FIXAS)

    def delete_despesa_fixa(self, row_id):
        self._get_ws(TAB_FIXAS).delete_rows(int(row_id))
        self._invalidate(TAB_FIXAS)

    # ── DESPESAS VARIÁVEIS ────────────────────────────────────────────────────

    def get_despesas_variaveis(self, mes_str):
        rows = self._for_month(TAB_VARIAVEIS, mes_str)
        for r in rows:
            r['valor'] = self._flt(r.get('valor'))
        return rows

    def get_all_despesas_variaveis(self):
        rows = list(self._load_tab(TAB_VARIAVEIS))
        for r in rows:
            r['valor'] = self._flt(r.get('valor'))
        return rows

    def insert_despesa_variavel(self, mes, data, descricao, valor):
        self._get_ws(TAB_VARIAVEIS).append_row([mes, data, descricao, str(valor or 0)])
        self._invalidate(TAB_VARIAVEIS)

    def update_despesa_variavel(self, row_id, mes, data, descricao, valor):
        ws = self._get_ws(TAB_VARIAVEIS)
        ws.update(f'A{int(row_id)}:D{int(row_id)}', [[mes, data, descricao, str(valor or 0)]])
        self._invalidate(TAB_VARIAVEIS)

    def delete_despesa_variavel(self, row_id):
        self._get_ws(TAB_VARIAVEIS).delete_rows(int(row_id))
        self._invalidate(TAB_VARIAVEIS)
