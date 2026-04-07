from flask import Flask, render_template, request, redirect, url_for, session, jsonify, make_response
from functools import wraps
import os
import calendar
from datetime import datetime, date
from dotenv import load_dotenv
import bcrypt
from sheets import SheetsDB

load_dotenv()

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'tesouraria-igreja-secret-2026')

# Garantir que a SECRET_KEY não é o valor padrão em produção
if app.secret_key == 'tesouraria-igreja-secret-2026' and os.environ.get('FLASK_ENV') == 'production':
    raise RuntimeError("SECRET_KEY não configurada para produção!")

db = SheetsDB()

MONTHS_PT = {
    1: 'Janeiro', 2: 'Fevereiro', 3: 'Março', 4: 'Abril',
    5: 'Maio', 6: 'Junho', 7: 'Julho', 8: 'Agosto',
    9: 'Setembro', 10: 'Outubro', 11: 'Novembro', 12: 'Dezembro'
}

DESPESAS_FIXAS_PADRAO = [
    'Côngrua Pastoral (IPLC e IPC)',
    'Passagem Ver. Moisés',
    'Cesta Pastoral',
    'Energia Elétrica',
    'Plano de Internet',
    'Zeladoria',
    'Supremo Concílio',
    'PPNB',
    'Água Mineral',
]


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated


def get_sundays(year, month):
    cal = calendar.monthcalendar(year, month)
    sundays = []
    for week in cal:
        if week[6] != 0:
            sundays.append(date(year, month, week[6]))
    return sundays


def fmt_brl(value):
    try:
        v = float(value or 0)
        return f"R$ {v:,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.')
    except Exception:
        return "R$ 0,00"


app.jinja_env.filters['brl'] = fmt_brl


def get_period():
    now = datetime.now()
    y_arg = request.args.get('year')
    m_arg = request.args.get('month')

    if y_arg:
        session['current_year'] = int(y_arg)
    if m_arg:
        session['current_month'] = int(m_arg)

    y = session.get('current_year', now.year)
    m = session.get('current_month', now.month)
    return y, m


# ── Core: agrega dados por mês a partir de dados já em memória ──────────────

def _summarize(entradas_all, fixas_all, variaveis_all, mes_str):
    """
    Agrega dados de um mês a partir de listas já carregadas em memória.
    Zero chamadas adicionais à API.
    """
    entradas   = [e for e in entradas_all   if e.get('mes') == mes_str]
    desp_fixas = [d for d in fixas_all      if d.get('mes') == mes_str]
    desp_var   = [d for d in variaveis_all  if d.get('mes') == mes_str]

    td = sum(float(e.get('dizimos', 0)) for e in entradas)
    to = sum(float(e.get('ofertas',  0)) for e in entradas)
    tx = sum(float(e.get('extra',    0)) for e in entradas)
    te = td + to + tx
    tf = sum(float(d.get('valor', 0)) for d in desp_fixas)
    tv = sum(float(d.get('valor', 0)) for d in desp_var)
    ts = tf + tv

    return {
        'entradas':       entradas,
        'desp_fixas':     desp_fixas,
        'desp_variaveis': desp_var,
        'total_dizimos':  td,
        'total_ofertas':  to,
        'total_extras':   tx,
        'total_entradas': te,
        'total_fixas':    tf,
        'total_variaveis':tv,
        'total_saidas':   ts,
        'saldo_mes':      te - ts,
    }


def get_monthly_summary(mes_str):
    """Busca 3 abas (com cache) e filtra em Python. Máx. 3 chamadas à API."""
    return _summarize(
        db.get_all_entradas(),
        db.get_all_despesas_fixas(),
        db.get_all_despesas_variaveis(),
        mes_str,
    )


def get_annual_summary(year):
    """
    Calcula todos os 12 meses em uma passagem — apenas 3 chamadas à API total.
    Cada mês recebe 'saldo_acumulado': o saldo em conta ao fim daquele mês
    (soma de todos os meses do ano até ele, sem contar anos anteriores aqui).
    Para o acumulado real desde o início, ver get_saldo_acumulado().
    """
    e_all = db.get_all_entradas()
    f_all = db.get_all_despesas_fixas()
    v_all = db.get_all_despesas_variaveis()

    # Saldo acumulado de anos anteriores (base de partida do ano)
    saldo_base = get_saldo_acumulado(f"{year}-01")

    meses  = []
    totais = dict(total_dizimos=0, total_ofertas=0, total_extras=0, total_entradas=0,
                  total_fixas=0, total_variaveis=0, total_saidas=0, saldo_mes=0)

    saldo_corrente = saldo_base
    for m in range(1, 13):
        ms = f"{year}-{m:02d}"
        s  = _summarize(e_all, f_all, v_all, ms)
        saldo_corrente += s['saldo_mes']
        meses.append({'mes_nome': MONTHS_PT[m], 'num': m, 'saldo_acumulado': saldo_corrente, **s})
        for k in totais:
            totais[k] += s[k]

    return meses, totais


def get_saldo_acumulado(mes_str):
    """
    Calcula o saldo acumulado desde o início até o mês anterior a mes_str.
    Representa o dinheiro em conta antes do mês atual.
    """
    year, month = map(int, mes_str.split('-'))

    e_all = db.get_all_entradas()
    f_all = db.get_all_despesas_fixas()
    v_all = db.get_all_despesas_variaveis()

    saldo_acumulado = 0.0

    # Soma todos os meses anteriores ao mês informado
    for y in range(2020, year + 1):
        for m in range(1, 13):
            # Para quando chegar ao mês atual
            if y == year and m >= month:
                break
            ms = f"{y}-{m:02d}"
            s = _summarize(e_all, f_all, v_all, ms)
            saldo_acumulado += s['saldo_mes']

    return saldo_acumulado


# ── PUBLIC ───────────────────────────────────────────────────────────────────

@app.route('/')
@login_required
def index():
    now  = datetime.now()
    year, month = get_period()

    # view: 'anual' (padrão) ou 'mensal'
    view  = request.args.get('view', 'anual')

    meses, totais = get_annual_summary(year)

    # Dados do mês selecionado (para exibição no modo mensal)
    mes_str = f"{year}-{month:02d}"
    mes_summary = get_monthly_summary(mes_str)

    # Saldo em conta do mês selecionado (acumulado até o fim do mês)
    saldo_anterior_mes = get_saldo_acumulado(mes_str)
    saldo_em_conta_mes = saldo_anterior_mes + mes_summary.get('saldo_mes', 0)

    # Saldo em conta do ano (acumulado total até dezembro)
    ultimo_mes = meses[-1]  # dezembro
    saldo_em_conta_ano = ultimo_mes['saldo_acumulado']

    return render_template('index.html',
        year=year, month=month, view=view,
        mes_nome=MONTHS_PT[month],
        months=MONTHS_PT,
        now=now,
        meses=meses,
        totais=totais,
        saldo_em_conta_ano=saldo_em_conta_ano,
        saldo_anterior_mes=saldo_anterior_mes,
        saldo_em_conta_mes=saldo_em_conta_mes,
        **{f'mes_{k}': v for k, v in mes_summary.items()},
    )


# ── AUTH ─────────────────────────────────────────────────────────────────────

@app.route('/login', methods=['GET', 'POST'])
def login():
    error = None
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').encode('utf-8')

        admin_user = os.environ.get('ADMIN_USER', 'tesoureiro')
        admin_hash = os.environ.get('ADMIN_PASSWORD_HASH', '')
        admin_pw   = os.environ.get('ADMIN_PASSWORD', '')

        ok = False
        if username == admin_user:
            if admin_hash and bcrypt.checkpw(password, admin_hash.encode('utf-8')):
                ok = True
            elif admin_pw and admin_pw == request.form.get('password'):
                ok = True

        if ok:
            session['user'] = username
            session.permanent = True
            return redirect(url_for('index'))

        error = 'Usuário ou senha inválidos.'

    return render_template('login.html', error=error)


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))


# ── ENTRADAS ─────────────────────────────────────────────────────────────────

@app.route('/admin/entradas')
@login_required
def admin_entradas():
    now   = datetime.now()
    year, month = get_period()
    mes_str = f"{year}-{month:02d}"

    sundays        = get_sundays(year, month)
    entradas_saved = db.get_entradas(mes_str)
    sunday_strs    = [d.strftime('%d/%m/%Y') for d in sundays]

    rows = []

    # DOMINGOS
    for ds in sunday_strs:
        saved = next((e for e in entradas_saved if e['data'] == ds), {})
        rows.append({
            'data': ds,
            'dizimos': saved.get('dizimos', ''),
            'ofertas': saved.get('ofertas', ''),
            'extra': saved.get('extra', ''),
            'descricao': saved.get('descricao', ''),
            'row_id': saved.get('row_id', ''),
            'tipo': 'domingo'
        })

    # EXTRAS — datas que não são domingos
    extras = [e for e in entradas_saved if e['data'] not in sunday_strs]

    for e in extras:
        rows.append({
            'data': e.get('data'),
            'dizimos': e.get('dizimos', ''),
            'ofertas': e.get('ofertas', ''),
            'extra': e.get('extra', ''),
            'row_id': e.get('row_id'),
            'descricao': e.get('descricao', ''),
            'tipo': 'extra'
        })

    td = sum(float(e.get('dizimos', 0) or 0) for e in entradas_saved)
    to = sum(float(e.get('ofertas',  0) or 0) for e in entradas_saved)
    tx = sum(float(e.get('extra',    0) or 0) for e in entradas_saved)

    return render_template('admin/entradas.html',
        year=year, month=month,
        mes_nome=MONTHS_PT[month],
        months=MONTHS_PT,
        mes_str=mes_str,
        rows=rows,
        total_dizimos=td,
        total_ofertas=to,
        total_extras=tx,
        total_entradas=td + to + tx,
        now=now
    )

@app.route('/admin/entradas/salvar', methods=['POST'])
@login_required
def salvar_entradas():
    try:
        data_json = request.get_json()

        mes_str  = data_json.get('mes')
        rows     = data_json.get('rows', [])

        updated = db.upsert_entradas_batch(mes_str, rows)

        return jsonify({'ok': True, 'rows': updated})

    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)})

@app.route('/admin/entradas/deletar', methods=['POST'])
@login_required
def deletar_entrada():
    try:
        data = request.get_json()
        row_id = data.get('row_id')

        if row_id:
            db.delete_entrada(row_id)

        return jsonify({'ok': True})

    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500

# ── DESPESAS FIXAS ───────────────────────────────────────────────────────────

@app.route('/admin/despesas-fixas')
@login_required
def admin_despesas_fixas():
    now   = datetime.now()
    year, month = get_period()
    mes_str = f"{year}-{month:02d}"

    saved     = db.get_despesas_fixas(mes_str)
    saved_map = {d['descricao']: d for d in saved}

    rows = []
    for desc in DESPESAS_FIXAS_PADRAO:
        s = saved_map.get(desc, {})
        rows.append({
            'descricao': desc,
            'valor':     s.get('valor', ''),
            'row_id':    s.get('row_id', ''),
            'padrao':    True,
        })
    for d in saved:
        if d['descricao'] not in DESPESAS_FIXAS_PADRAO:
            rows.append({
                'descricao': d['descricao'],
                'valor':     d.get('valor', ''),
                'row_id':    d.get('row_id', ''),
                'padrao':    False,
            })

    total = sum(float(d.get('valor', 0) or 0) for d in saved)

    return render_template('admin/despesas_fixas.html',
        year=year, month=month,
        mes_nome=MONTHS_PT[month],
        months=MONTHS_PT,
        mes_str=mes_str,
        rows=rows,
        total=total,
        now=now
    )


@app.route('/admin/despesas-fixas/salvar', methods=['POST'])
@login_required
def salvar_despesas_fixas():
    data_json = request.get_json()
    mes_str   = data_json.get('mes')
    rows      = data_json.get('rows', [])
    db.upsert_fixas_batch(mes_str, rows)
    return jsonify({'ok': True})


@app.route('/admin/despesas-fixas/deletar', methods=['POST'])
@login_required
def deletar_despesa_fixa():
    data_json = request.get_json()
    db.delete_despesa_fixa(data_json.get('row_id'))
    return jsonify({'ok': True})


# ── DESPESAS VARIÁVEIS ───────────────────────────────────────────────────────

@app.route('/admin/despesas-variaveis')
@login_required
def admin_despesas_variaveis():
    now   = datetime.now()
    year, month = get_period()
    mes_str = f"{year}-{month:02d}"

    rows  = db.get_despesas_variaveis(mes_str)
    total = sum(float(d.get('valor', 0) or 0) for d in rows)

    return render_template('admin/despesas_variaveis.html',
        year=year, month=month,
        mes_nome=MONTHS_PT[month],
        months=MONTHS_PT,
        mes_str=mes_str,
        rows=rows,
        total=total,
        now=now
    )


@app.route('/admin/despesas-variaveis/salvar', methods=['POST'])
@login_required
def salvar_despesa_variavel():
    data_json = request.get_json()
    mes_str   = data_json.get('mes')
    row       = data_json.get('row', {})
    if row.get('row_id'):
        db.update_despesa_variavel(row['row_id'], mes_str,
                                   row['data'], row['descricao'], row['valor'])
    else:
        db.insert_despesa_variavel(mes_str, row['data'], row['descricao'], row['valor'])
    return jsonify({'ok': True})


@app.route('/admin/despesas-variaveis/deletar', methods=['POST'])
@login_required
def deletar_despesa_variavel():
    data_json = request.get_json()
    db.delete_despesa_variavel(data_json.get('row_id'))
    return jsonify({'ok': True})

@app.route('/admin/despesas-variaveis/salvar-tudo', methods=['POST'])
@login_required
def salvar_tudo_variaveis():
    data_json = request.get_json()
    mes_str = data_json.get('mes')
    rows = data_json.get('rows', [])

    for row in rows:
        if row.get('row_id'):
            db.update_despesa_variavel(
                row['row_id'], mes_str,
                row['data'], row['descricao'], row['valor']
            )
        else:
            db.insert_despesa_variavel(
                mes_str,
                row['data'], row['descricao'], row['valor']
            )

    return jsonify({'ok': True})


# ── RELATÓRIOS ────────────────────────────────────────────────────────────────

@app.route('/admin/relatorio-mensal')
@login_required
def relatorio_mensal():
    now   = datetime.now()
    year, month = get_period()
    mes_str = f"{year}-{month:02d}"

    summary = get_monthly_summary(mes_str)
    saldo_anterior = get_saldo_acumulado(mes_str)
    saldo_mes = summary.get('saldo_mes', 0)
    saldo_conta = saldo_anterior + saldo_mes

    return render_template(
        'admin/relatorio_mensal.html',
        #'admin/relatorio_pdf.html',
        year=year,
        month=month,
        mes_nome=MONTHS_PT[month],
        months=MONTHS_PT,
        mes_str=mes_str,
        now=now,
        **summary,
        saldo_anterior=saldo_anterior,
        saldo_conta=saldo_conta
    )

@app.route('/admin/relatorio-anual')
@login_required
def relatorio_anual():
    now   = datetime.now()
    year, month = get_period()
    meses, totais = get_annual_summary(year)

    if meses:
        saldo_em_conta_ano = meses[-1]['saldo_acumulado']
    else:
        saldo_em_conta_ano = 0

    return render_template('admin/relatorio_anual.html',
        year=year, months=MONTHS_PT,
        meses=meses, totais=totais, now=now,
        saldo_em_conta_ano=saldo_em_conta_ano
    )


# ── PDF ───────────────────────────────────────────────────────────────────────

@app.route('/admin/relatorio-mensal/pdf')
@login_required
def relatorio_mensal_pdf():
    now     = datetime.now()
    year, month = get_period()
    mes_str = f"{year}-{month:02d}"
    summary = get_monthly_summary(mes_str)

    saldo_anterior = get_saldo_acumulado(mes_str)
    saldo_conta = saldo_anterior + summary.get('saldo_mes', 0)

    html = render_template('admin/relatorio_pdf.html',
        year=year, month=month,
        mes_nome=MONTHS_PT[month],
        mes_str=mes_str,
        now=now,
        saldo_anterior=saldo_anterior,
        saldo_conta=saldo_conta,
        **summary
    )

    try:
        from weasyprint import HTML
        pdf_bytes = HTML(string=html, base_url=request.host_url).write_pdf()
        response  = make_response(pdf_bytes)
        response.headers['Content-Type']        = 'application/pdf'
        response.headers['Content-Disposition'] = f'attachment; filename=relatorio_{mes_str}.pdf'
        return response
    except Exception as e:
        return html, 200, {'Content-Type': 'text/html'}


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    debug = os.environ.get('FLASK_DEBUG', 'false').lower() == 'true'
    app.run(host='0.0.0.0', port=port, debug=debug)
