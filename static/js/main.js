/* ── Utilities ─────────────────────────────────────────────────────── */

function fmtBRL(v) {
  const n = parseFloat(v) || 0;
  return n.toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' });
}

function parseBRL(s) {
  if (!s) return 0;

  s = String(s).trim();

  if (s.includes(',')) {
    s = s.replace(/\./g, '').replace(',', '.');
  }

  const n = parseFloat(s);
  return isNaN(n) ? 0 : n;
}

/* Currency input mask */
document.addEventListener('input', (e) => {
  if (!e.target.classList.contains('currency')) return;
  let raw = e.target.value.replace(/\D/g, '');
  if (!raw) { e.target.value = ''; return; }
  const num = parseInt(raw, 10) / 100;
  e.target.value = num.toLocaleString('pt-BR', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
});

/* ── Máscara de data dd/mm/aaaa ────────────────────────────────────── */
function applyDateMask(input) {
  input.addEventListener('input', function () {
    let v = this.value.replace(/\D/g, '');
    if (v.length > 8) v = v.slice(0, 8);
    if (v.length >= 5) {
      v = v.slice(0, 2) + '/' + v.slice(2, 4) + '/' + v.slice(4);
    } else if (v.length >= 3) {
      v = v.slice(0, 2) + '/' + v.slice(2);
    }
    this.value = v;
  });
}

function initDateMasks() {
  document.querySelectorAll('[data-col="data"], .date-mask').forEach(applyDateMask);
}

/* ── Toast helper ──────────────────────────────────────────────────── */
function showToast(msg, type = 'success') {
  let toast = document.getElementById('saveToast');
  if (!toast) {
    toast = document.createElement('div');
    toast.id = 'saveToast';
    toast.style.cssText = 'position:fixed;bottom:1.5rem;right:1.5rem;z-index:9999;';
    document.body.appendChild(toast);
  }
  const color = type === 'success' ? '#1a4731' : '#c0392b';
  toast.innerHTML = `
    <div style="background:${color};color:#fff;padding:.8rem 1.4rem;border-radius:10px;
                box-shadow:0 4px 16px rgba(0,0,0,.25);font-size:.9rem;font-weight:500;
                display:flex;align-items:center;gap:.5rem;min-width:220px;">
      <i class="bi bi-${type === 'success' ? 'check-circle' : 'exclamation-triangle'}-fill"></i>
      ${msg}
    </div>`;
  setTimeout(() => toast.innerHTML = '', 3000);
}

/* ── Month selector ────────────────────────────────────────────────── */
function initMonthSelector() {
  const yearSel  = document.getElementById('yearSel');
  const monthSel = document.getElementById('monthSel');
  if (!yearSel || !monthSel) return;

  function navigate() {
    const url = new URL(window.location.href);
    url.searchParams.set('year', yearSel.value);
    url.searchParams.set('month', monthSel.value);
    window.location.href = url.toString();
  }
  yearSel.addEventListener('change', navigate);
  monthSel.addEventListener('change', navigate);
}

/* ── Auto-recalc totals ─────────────────────────────────────────────── */
function calcRowTotal(row) {
  const dizimos = parseBRL(row.querySelector('[data-col="dizimos"]')?.value);
  const ofertas = parseBRL(row.querySelector('[data-col="ofertas"]')?.value);
  const totalEl = row.querySelector('[data-col="total"]');
  if (totalEl) totalEl.textContent = fmtBRL(dizimos + ofertas);
}

function calcTableTotals() {
  let sumDizimos = 0, sumOfertas = 0, sumValor = 0;

  document.querySelectorAll('tr[data-row]').forEach(row => {
    const dEl = row.querySelector('[data-col="dizimos"]');
    const oEl = row.querySelector('[data-col="ofertas"]');
    const vEl = row.querySelector('[data-col="valor"]');
    if (dEl) sumDizimos += parseBRL(dEl.value);
    if (oEl) sumOfertas += parseBRL(oEl.value);
    if (vEl) sumValor   += parseBRL(vEl.value);
    calcRowTotal(row);
  });

  const setEl = (id, v) => { const el = document.getElementById(id); if (el) el.textContent = fmtBRL(v); };
  setEl('totalDizimos', sumDizimos);
  setEl('totalOfertas', sumOfertas);
  setEl('totalEntradas', sumDizimos + sumOfertas);
  setEl('totalValor', sumValor);
}

document.addEventListener('input', (e) => {
  if (!e.target.classList.contains('currency')) return;
  const row = e.target.closest('tr[data-row]');
  if (row) calcRowTotal(row);
  calcTableTotals();
});

/* ── Save entries (Entradas) ───────────────────────────────────────── */
async function saveTable(mes) {
  const trs = document.querySelectorAll('#entradasTbody tr');
  const rows = [];

  trs.forEach(row => {
    const get = (col) => row.querySelector(`[data-col="${col}"]`)?.value?.trim() || '';

    rows.push({
      row_id: row.dataset.rowId || '',
      data: get('data'),
      dizimos: row.dataset.tipo === 'domingo' ? parseBRL(get('dizimos')) || 0 : 0,
      ofertas: parseBRL(get('ofertas')) || 0,
      descricao: get('descricao') || '',
      tipo: row.dataset.tipo || 'domingo'
    });
  });

  const endpoint = document.getElementById('saveEndpoint').value;

  try {
    const res = await fetch(endpoint, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ mes, rows })
    });

    const json = await res.json();

    if (json.ok) {
      // Atualiza row_id nas linhas novas
      if (json.rows) {
        json.rows.forEach((r, index) => {
          if (trs[index] && !trs[index].dataset.rowId && r.row_id) {
            trs[index].dataset.rowId = r.row_id;
          }
        });
      }

      recalcEntradas();
      showToast('Salvo com sucesso!');

    } else {
      showToast(json.error || 'Erro ao salvar', 'error');
    }

  } catch {
    showToast('Erro de conexão', 'error');
  }
}

/* ── Add variable expense row ─────────────────────────────────────── */
function addVariavelRow(mes) {
  const tbody = document.getElementById('varTbody');
  if (!tbody) return;
  const idx = Date.now();
  const tr = document.createElement('tr');
  tr.dataset.row = idx;
  tr.dataset.rowId = '';
  tr.innerHTML = `
    <td><input type="text" class="form-control form-control-sm date-mask" data-col="data" placeholder="DD/MM/AAAA" maxlength="10" /></td>
    <td><input type="text" class="form-control form-control-sm" data-col="descricao" placeholder="Descrição" /></td>
    <td><input type="text" class="form-control form-control-sm currency text-end" data-col="valor" placeholder="0,00" /></td>
    <td class="text-center">
      <button class="btn btn-sm btn-danger" onclick="saveVariavel(this, '${mes}')"><i class="bi bi-floppy"></i></button>
      <button class="btn btn-sm btn-outline-danger ms-1" onclick="this.closest('tr').remove(); calcTableTotals()"><i class="bi bi-trash"></i></button>
    </td>`;
  tbody.appendChild(tr);
  const dateInput = tr.querySelector('[data-col="data"]');
  applyDateMask(dateInput);
  dateInput.focus();
}

async function saveVariavel(btn, mes) {
  const tr = btn.closest('tr');
  const row = {
    row_id:    tr.dataset.rowId || '',
    data:      tr.querySelector('[data-col="data"]')?.value?.trim() || '',
    descricao: tr.querySelector('[data-col="descricao"]')?.value?.trim() || '',
    valor:     parseBRL(tr.querySelector('[data-col="valor"]')?.value) || 0,
  };

  if (!row.descricao) { showToast('Preencha a descrição.', 'error'); return; }

  try {
    const res = await fetch('/admin/despesas-variaveis/salvar', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ mes, row }),
    });
    const json = await res.json();
    if (json.ok) { showToast('Salvo!'); window.location.reload(); }
    else showToast('Erro ao salvar.', 'error');
  } catch { showToast('Erro de conexão.', 'error'); }
}

async function saveVariaveis(mes) {
  const rows = [];

  document.querySelectorAll('tr[data-row]').forEach(tr => {
    const data = tr.querySelector('[data-col="data"]')?.value?.trim() || '';
    const desc = tr.querySelector('[data-col="descricao"]')?.value?.trim() || '';
    const val  = parseBRL(tr.querySelector('[data-col="valor"]')?.value) || 0;

    if (desc || val) {
      rows.push({
        row_id: tr.dataset.rowId || '',
        data,
        descricao: desc,
        valor: val
      });
    }
  });

  if (!rows.length) {
    showToast('Nada para salvar.', 'error');
    return;
  }

  try {
    const res = await fetch('/admin/despesas-variaveis/salvar-tudo', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ mes, rows })
    });

    const json = await res.json();

    if (json.ok) {
      showToast('Despesas salvas!');
      setTimeout(() => window.location.reload(), 500);
    } else {
      showToast('Erro ao salvar', 'error');
    }

  } catch {
    showToast('Erro de conexão', 'error');
  }
}

async function deleteVariavel(rowId) {
  if (!confirm('Remover este lançamento?')) return;
  try {
    const res = await fetch('/admin/despesas-variaveis/deletar', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ row_id: rowId }),
    });
    const json = await res.json();
    if (json.ok) window.location.reload();
    else showToast('Erro ao remover.', 'error');
  } catch { showToast('Erro de conexão.', 'error'); }
}

async function deleteFixa(rowId) {
  if (!confirm('Remover esta despesa?')) return;
  try {
    const res = await fetch('/admin/despesas-fixas/deletar', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ row_id: rowId }),
    });
    const json = await res.json();
    if (json.ok) window.location.reload();
    else showToast('Erro ao remover.', 'error');
  } catch { showToast('Erro de conexão.', 'error'); }
}

/* ── Add fixed expense row ────────────────────────────────────────── */
function addFixaRow(mes) {
  const tbody = document.getElementById('fixaTbody');
  if (!tbody) return;
  const idx = Date.now();
  const tr = document.createElement('tr');
  tr.dataset.row = idx;
  tr.dataset.rowId = '';
  tr.innerHTML = `
    <td><input type="text" class="form-control form-control-sm" data-col="descricao" placeholder="Nome da despesa" /></td>
    <td><input type="text" class="form-control form-control-sm currency text-end" data-col="valor" placeholder="0,00" /></td>
    <td class="text-center">
      <button class="btn btn-sm btn-danger" onclick="saveFixaRow(this, '${mes}')"><i class="bi bi-floppy"></i></button>
      <button class="btn btn-sm btn-outline-danger ms-1" onclick="this.closest('tr').remove(); calcTableTotals()"><i class="bi bi-trash"></i></button>
    </td>`;
  tbody.appendChild(tr);
  tr.querySelector('[data-col="descricao"]').focus();
}

async function saveFixaRow(btn, mes) {
  const tr = btn.closest('tr');
  const row = {
    row_id:    tr.dataset.rowId || '',
    descricao: tr.querySelector('[data-col="descricao"]')?.value?.trim() || '',
    valor:     parseBRL(tr.querySelector('[data-col="valor"]')?.value) || 0,
  };
  if (!row.descricao) { showToast('Preencha a descrição.', 'error'); return; }
  try {
    const res = await fetch('/admin/despesas-fixas/salvar', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ mes, rows: [row] }),
    });
    const json = await res.json();
    if (json.ok) { showToast('Salvo!'); window.location.reload(); }
    else showToast('Erro ao salvar.', 'error');
  } catch { showToast('Erro de conexão.', 'error'); }
}

/* ── Init ──────────────────────────────────────────────────────────── */
document.addEventListener('DOMContentLoaded', () => {
  initMonthSelector();
  calcTableTotals();
  initDateMasks();
});

/* ── Admin period navigation ─────────────────────────────────────────── */
function adminNavigate() {
  const url = new URL(window.location.href);
  const y = document.getElementById('yearSel');
  const m = document.getElementById('monthSel');
  if (y) url.searchParams.set('year',  y.value);
  if (m) url.searchParams.set('month', m.value);
  window.location.href = url.toString();
}
