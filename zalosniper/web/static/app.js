// ── Theme ──
const theme = localStorage.getItem('theme') || 'dark';
document.documentElement.setAttribute('data-theme', theme);

function toggleTheme() {
  const current = document.documentElement.getAttribute('data-theme');
  const next = current === 'dark' ? 'light' : 'dark';
  document.documentElement.setAttribute('data-theme', next);
  localStorage.setItem('theme', next);
  const btn = document.getElementById('theme-btn');
  if (btn) btn.textContent = next === 'dark' ? '🌙' : '☀️';
}

// ── API helpers ──
async function api(method, path, body) {
  const opts = { method, headers: {'Content-Type': 'application/json'}, credentials: 'same-origin' };
  if (body !== undefined) opts.body = JSON.stringify(body);
  const resp = await fetch(path, opts);
  if (resp.status === 401) { window.location = '/'; return null; }
  return resp.json();
}
const GET = path => api('GET', path);
const POST = (path, body) => api('POST', path, body);
const PATCH = (path, body) => api('PATCH', path, body);
const PUT = (path, body) => api('PUT', path, body);
const DELETE = path => api('DELETE', path);

// ── Toast notifications ──
function toast(msg, type = 'success') {
  const el = document.createElement('div');
  el.className = `alert alert-${type}`;
  el.style.cssText = 'position:fixed;top:20px;right:20px;z-index:9999;min-width:280px;animation:fadeIn .2s';
  el.textContent = msg;
  document.body.appendChild(el);
  setTimeout(() => el.remove(), 3000);
}

// ── Confirm dialog ──
function confirm_action(msg) { return window.confirm(msg); }

// ── Toggle switch ──
function makeToggle(on, onChange) {
  const btn = document.createElement('button');
  btn.className = `toggle ${on ? 'on' : ''}`;
  btn.onclick = async () => {
    const newOn = !btn.classList.contains('on');
    const ok = await onChange(newOn);
    if (ok !== false) btn.classList.toggle('on', newOn);
  };
  return btn;
}

// ── Status pill ──
function statusPill(status) {
  const map = { done: 'pill-done', pending: 'pill-pending', rejected: 'pill-rejected',
                error: 'pill-error', approved: 'pill-done', expired: 'pill-rejected' };
  return `<span class="pill ${map[status] || 'pill-pending'}">${status.toUpperCase()}</span>`;
}

// ── Logout ──
async function logout() {
  await POST('/api/auth/logout');
  window.location = '/';
}

// ── Apply theme button label on load ──
document.addEventListener('DOMContentLoaded', () => {
  const btn = document.getElementById('theme-btn');
  if (btn) btn.textContent = (localStorage.getItem('theme') || 'dark') === 'dark' ? '🌙' : '☀️';
});
