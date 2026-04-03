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

db = SheetsDB()

MONTHS_PT = {
    1: 'Janeiro', 2: 'Fevereiro', 3: 'Março', 4: 'Abril',
    5: 'Maio', 6: 'Junho', 7: 'Julho', 8: 'Agosto',
    9: 'Setembro', 10: 'Outubro', 11: 'Novembro', 12: 'Dezembro'
}

DESPESAS_FIXAS_PADRAO = [
    'Côngrua Pastoral (IPLC e IPC)',
    'Energia Elétrica',
    'Plano de Internet',
    'Zeladoria',
    'Água Mineral',
    'Supremo Concílio',
    'PPNB',
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
    te = td + to
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
    Calcula todos os 12 meses em uma passagem — apenas 3 chamadas à API total
    (pois os dados das 3 abas já estão em cache após o primeiro acesso).
    """
    e_all = db.get_all_entradas()
    f_all = db.get_all_despesas_fixas()
    v_all = db.get_all_despesas_variaveis()

    meses  = []
    totais = dict(total_dizimos=0, total_ofertas=0, total_entradas=0, total_extras=0,
                  total_fixas=0, total_variaveis=0, total_saidas=0, saldo_mes=0)

    for m in range(1, 13):
        ms = f"{year}-{m:02d}"
        s  = _summarize(e_all, f_all, v_all, ms)
        meses.append({'mes_nome': MONTHS_PT[m], 'num': m, **s})
        for k in totais:
            totais[k] += s[k]

    return meses, totais


# ── PUBLIC ───────────────────────────────────────────────────────────────────

@app.route('/')
@login_required
def index():
    now  = datetime.now()
    year = int(request.args.get('year', now.year))

    # view: 'anual' (padrão) ou 'mensal'
    view  = request.args.get('view', 'anual')
    month = int(request.args.get('month', now.month))

    meses, totais = get_annual_summary(year)

    # Dados do mês selecionado (para exibição no modo mensal)
    mes_str = f"{year}-{month:02d}"
    mes_summary = get_monthly_summary(mes_str)

    return render_template('index.html',
        year=year, month=month, view=view,
        mes_nome=MONTHS_PT[month],
        months=MONTHS_PT,
        now=now,
        meses=meses,
        totais=totais,
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
            # NÃO limpa cache no login — dados ainda são válidos
            return redirect(url_for('index'))

        error = 'Usuário ou senha inválidos.'

    return render_template('login.html', error=error)


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated

# ── ADMIN DASHBOARD ───────────────────────────────────────────────────────────

@app.route('/')
@login_required
def admin_dashboard():
    now   = datetime.now()
    year  = int(request.args.get('year',  now.year))
    month = int(request.args.get('month', now.month))
    mes_str = f"{year}-{month:02d}"

    # 3 chamadas à API (com cache); depois tudo é Python
    summary      = get_monthly_summary(mes_str)
    meses, _     = get_annual_summary(year)

    # quick annual stats for chart
    annual = [{'mes': m['mes_nome'], 'num': m['num'],
               'entradas': m['total_entradas'],
               'saidas':   m['total_saidas'],
               'saldo':    m['saldo_mes']} for m in meses]

    return render_template('admin/index.html',
        year=year, month=month,
        mes_nome=MONTHS_PT[month],
        months=MONTHS_PT,
        now=now,
        annual=annual,
        **summary
    )


# ── ENTRADAS ─────────────────────────────────────────────────────────────────

@app.route('/admin/entradas')
@login_required
def admin_entradas():
    now   = datetime.now()
    year  = int(request.args.get('year',  now.year))
    month = int(request.args.get('month', now.month))
    mes_str = f"{year}-{month:02d}"

    sundays        = get_sundays(year, month)
    entradas_saved = db.get_entradas(mes_str)
    sundays = get_sundays(year, month)
    sunday_strs = [d.strftime('%d/%m/%Y') for d in sundays]

    rows = []

    # DOMINGOS
    for ds in sunday_strs:
        saved = next((e for e in entradas_saved if e['data'] == ds), {})
        rows.append({
            'data': ds,
            'dizimos': saved.get('dizimos', ''),
            'ofertas': saved.get('ofertas', ''),
            'descricao': saved.get('descricao', ''),
            'row_id': saved.get('row_id', ''),
            'tipo': 'domingo'
        })

    # EXTRAS
    extras = [e for e in entradas_saved if e['data'] not in sunday_strs]

    for e in extras:
        rows.append({
            'data': e.get('data'),
            'dizimos': 0,
            'ofertas': e.get('ofertas', ''),
            'row_id': e.get('row_id'),
            'descricao': e.get('descricao', ''),
            'tipo': 'extra'
        })

    td = sum(float(e.get('dizimos', 0) or 0) for e in entradas_saved)
    to = sum(float(e.get('ofertas',  0) or 0) for e in entradas_saved)

    return render_template('admin/entradas.html',
        year=year, month=month,
        mes_nome=MONTHS_PT[month],
        months=MONTHS_PT,
        mes_str=mes_str,
        rows=rows,
        total_dizimos=td,
        total_ofertas=to,
        total_entradas=td + to,
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
        print('ERRO AO DELETAR:', e)
        return jsonify({'ok': False, 'error': str(e)}), 500

# ── DESPESAS FIXAS ───────────────────────────────────────────────────────────

@app.route('/admin/despesas-fixas')
@login_required
def admin_despesas_fixas():
    now   = datetime.now()
    year  = int(request.args.get('year',  now.year))
    month = int(request.args.get('month', now.month))
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
    year  = int(request.args.get('year',  now.year))
    month = int(request.args.get('month', now.month))
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
    year  = int(request.args.get('year',  now.year))
    month = int(request.args.get('month', now.month))
    mes_str = f"{year}-{month:02d}"

    summary = get_monthly_summary(mes_str)
    saldo_anterior = get_saldo_anterior(mes_str)
    saldo_mes = summary.get('saldo_mes', 0)
    saldo_conta = saldo_anterior + saldo_mes

    return render_template(
        'admin/relatorio_mensal.html',
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
    year  = int(request.args.get('year', now.year))
    meses, totais = get_annual_summary(year)

    return render_template('admin/relatorio_anual.html',
        year=year, months=MONTHS_PT,
        meses=meses, totais=totais, now=now
    )

def get_saldo_anterior(mes_str):
    year, month = map(int, mes_str.split('-'))

    if month == 1:
        prev_year = year - 1
        prev_month = 12
    else:
        prev_year = year
        prev_month = month - 1

    prev_mes = f"{prev_year}-{prev_month:02d}"
    resumo = get_monthly_summary(prev_mes)

    return resumo['saldo_mes']


# ── PDF ───────────────────────────────────────────────────────────────────────

@app.route('/admin/relatorio-mensal/pdf')
@login_required
def relatorio_mensal_pdf():
    now     = datetime.now()
    year    = int(request.args.get('year',  now.year))
    month   = int(request.args.get('month', now.month))
    mes_str = f"{year}-{month:02d}"
    summary = get_monthly_summary(mes_str)

    html = render_template('admin/relatorio_pdf.html',
        year=year, month=month,
        mes_nome=MONTHS_PT[month],
        mes_str=mes_str,
        now=now,
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
        print("Erro PDF:", e)
        return html, 200, {'Content-Type': 'text/html'}


# ── API JSON ──────────────────────────────────────────────────────────────────

@app.route('/api/resumo/<mes_str>')
def api_resumo(mes_str):
    s = get_monthly_summary(mes_str)
    # remove listas para não expor dados internos na API pública
    return jsonify({k: v for k, v in s.items() if not isinstance(v, list)})


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port,
            debug=os.environ.get('FLASK_DEBUG', 'false').lower() == 'true')
