'use strict';

const PLATFORMS = ['LinkedIn', 'Twitter / X', 'Instagram', 'Facebook', 'Email', 'Phone', 'Referral', 'Other'];
const STATUSES  = ['New', 'Contacted', 'Qualified', 'Proposal Sent', 'Closed Won', 'Closed Lost'];

const STATUS_CLASS = {
  'New':           's-new',
  'Contacted':     's-contacted',
  'Qualified':     's-qualified',
  'Proposal Sent': 's-proposal',
  'Closed Won':    's-won',
  'Closed Lost':   's-lost',
};

// ── State ──────────────────────────────────────────────────────────────────

let leads    = JSON.parse(localStorage.getItem('cl-leads') || '[]');
let editingId = null;

function persist() {
  localStorage.setItem('cl-leads', JSON.stringify(leads));
}

function uid() {
  return Date.now().toString(36) + Math.random().toString(36).slice(2, 7);
}

function fmtDate(iso) {
  return new Date(iso).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
}

function esc(str) {
  return String(str ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

// ── Render ─────────────────────────────────────────────────────────────────

function renderStats() {
  const counts = {};
  STATUSES.forEach(s => { counts[s] = 0; });
  leads.forEach(l => { counts[l.status] = (counts[l.status] || 0) + 1; });

  const chips = [{ label: 'Total', count: leads.length }];
  STATUSES.forEach(s => { if (counts[s] > 0) chips.push({ label: s, count: counts[s] }); });

  document.getElementById('stats-bar').innerHTML = chips
    .map(c => `<div class="stat-chip"><span class="count">${c.count}</span><span>${esc(c.label)}</span></div>`)
    .join('');
}

function getFiltered() {
  const q  = document.getElementById('search').value.trim().toLowerCase();
  const fp = document.getElementById('filter-platform').value;
  const fs = document.getElementById('filter-status').value;

  return leads
    .filter(l => {
      if (q && !l.name.toLowerCase().includes(q) && !(l.company || '').toLowerCase().includes(q)) return false;
      if (fp && l.platform !== fp) return false;
      if (fs && l.status  !== fs) return false;
      return true;
    })
    .sort((a, b) => b.createdAt.localeCompare(a.createdAt));
}

function renderLeads() {
  const filtered = getFiltered();
  const container = document.getElementById('leads-container');

  if (filtered.length === 0) {
    container.innerHTML = `
      <div class="empty-state">
        <h3>${leads.length === 0 ? 'No leads yet' : 'No leads match your filters'}</h3>
        <p>${leads.length === 0 ? 'Click "+ Add Lead" to start tracking.' : 'Try adjusting the search or filters.'}</p>
      </div>`;
    return;
  }

  container.innerHTML = filtered.map(l => `
    <div class="lead-card">
      <div class="card-top">
        <div>
          <div class="card-name">${esc(l.name)}</div>
          ${l.company ? `<div class="card-company">${esc(l.company)}</div>` : ''}
        </div>
        <div class="badges">
          <span class="badge badge-platform">${esc(l.platform)}</span>
          <span class="badge ${STATUS_CLASS[l.status] || 's-new'}">${esc(l.status)}</span>
        </div>
      </div>
      ${l.contact ? `<div class="card-contact">&#x2709;&#xFE0F; ${esc(l.contact)}</div>` : ''}
      ${l.notes   ? `<div class="card-notes">${esc(l.notes)}</div>` : ''}
      <div class="card-footer">
        <span class="card-date">${fmtDate(l.createdAt)}</span>
        <div class="card-actions">
          <button class="btn-sm"        onclick="openEdit('${l.id}')">Edit</button>
          <button class="btn-sm danger" onclick="removeLead('${l.id}')">Delete</button>
        </div>
      </div>
    </div>`).join('');
}

function render() {
  renderStats();
  renderLeads();
}

// ── CRUD ───────────────────────────────────────────────────────────────────

window.removeLead = function (id) {
  if (!confirm('Delete this lead?')) return;
  leads = leads.filter(l => l.id !== id);
  persist();
  render();
};

window.openEdit = function (id) {
  const lead = leads.find(l => l.id === id);
  if (!lead) return;
  editingId = id;
  document.getElementById('modal-title').textContent = 'Edit Lead';

  const f = document.getElementById('lead-form');
  f.elements.name.value     = lead.name;
  f.elements.company.value  = lead.company  || '';
  f.elements.platform.value = lead.platform;
  f.elements.status.value   = lead.status;
  f.elements.contact.value  = lead.contact  || '';
  f.elements.notes.value    = lead.notes    || '';

  hideError();
  openModal();
};

// ── Modal ──────────────────────────────────────────────────────────────────

function openModal() { document.getElementById('modal').classList.remove('hidden'); }
function closeModal() {
  document.getElementById('modal').classList.add('hidden');
  editingId = null;
  document.getElementById('lead-form').reset();
  hideError();
}

function showError(msg) {
  const el = document.getElementById('form-error');
  el.textContent = msg;
  el.classList.remove('hidden');
}
function hideError() { document.getElementById('form-error').classList.add('hidden'); }

// ── Form submit ────────────────────────────────────────────────────────────

document.getElementById('lead-form').addEventListener('submit', e => {
  e.preventDefault();
  const f = e.target;
  const name = f.elements.name.value.trim();
  if (!name) { showError('Name is required.'); return; }

  const data = {
    name,
    company:  f.elements.company.value.trim(),
    platform: f.elements.platform.value,
    status:   f.elements.status.value,
    contact:  f.elements.contact.value.trim(),
    notes:    f.elements.notes.value.trim(),
  };

  if (editingId) {
    const idx = leads.findIndex(l => l.id === editingId);
    if (idx >= 0) leads[idx] = { ...leads[idx], ...data };
  } else {
    leads.push({ id: uid(), createdAt: new Date().toISOString(), ...data });
  }

  persist();
  closeModal();
  render();
});

// ── Export CSV ─────────────────────────────────────────────────────────────

function exportCSV() {
  const headers = ['Name', 'Company', 'Platform', 'Status', 'Contact', 'Notes', 'Added'];
  const rows = leads.map(l =>
    [l.name, l.company || '', l.platform, l.status, l.contact || '', l.notes || '', l.createdAt]
  );
  const csv = [headers, ...rows]
    .map(r => r.map(c => `"${String(c).replace(/"/g, '""')}"`).join(','))
    .join('\n');

  const blob = new Blob([csv], { type: 'text/csv' });
  const url  = URL.createObjectURL(blob);
  const a    = Object.assign(document.createElement('a'), { href: url, download: 'leads.csv' });
  a.click();
  URL.revokeObjectURL(url);
}

// ── Wiring ─────────────────────────────────────────────────────────────────

document.getElementById('add-btn').addEventListener('click', () => {
  editingId = null;
  document.getElementById('modal-title').textContent = 'Add Lead';
  document.getElementById('lead-form').reset();
  hideError();
  openModal();
});

document.getElementById('cancel-btn').addEventListener('click', closeModal);
document.getElementById('export-btn').addEventListener('click', exportCSV);

document.getElementById('modal').addEventListener('click', e => {
  if (e.target === document.getElementById('modal')) closeModal();
});

document.getElementById('search').addEventListener('input', renderLeads);
document.getElementById('filter-platform').addEventListener('change', renderLeads);
document.getElementById('filter-status').addEventListener('change', renderLeads);

// Close on Escape
document.addEventListener('keydown', e => {
  if (e.key === 'Escape' && !document.getElementById('modal').classList.contains('hidden')) closeModal();
});

// ── Populate filter/form selects ───────────────────────────────────────────

function populateSelect(el, options) {
  options.forEach(v => {
    const opt = document.createElement('option');
    opt.value = opt.textContent = v;
    el.appendChild(opt);
  });
}

populateSelect(document.getElementById('filter-platform'), PLATFORMS);
populateSelect(document.getElementById('filter-status'),   STATUSES);
populateSelect(document.getElementById('f-platform'),      PLATFORMS);
populateSelect(document.getElementById('f-status'),        STATUSES);

// ── Init ───────────────────────────────────────────────────────────────────

render();
