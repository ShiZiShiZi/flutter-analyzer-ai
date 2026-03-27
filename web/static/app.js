/* app.js — 页面交互（手动刷新，无 SSE） */
'use strict';

// ── API helper ───────────────────────────────────────────────────────────────
async function apiFetch(url, method = 'GET', body = null) {
  const opts = { method, headers: { 'Content-Type': 'application/json' } };
  if (body !== null) opts.body = JSON.stringify(body);
  const resp = await fetch(url, opts);
  const data = await resp.json();
  if (!resp.ok) throw new Error(data.detail || resp.statusText);
  return data;
}

// ── Toast notifications ───────────────────────────────────────────────────────
function showToast(msg, type = 'info', duration = 3500) {
  const c = document.getElementById('toast-container');
  if (!c) return;
  const el = document.createElement('div');
  el.className = `toast ${type === 'error' ? 'error' : type === 'success' ? 'success' : ''}`;
  el.textContent = msg;
  c.appendChild(el);
  setTimeout(() => el.remove(), duration);
}

// ── Filter bar ────────────────────────────────────────────────────────────────
loadPluginCounts();

// ── Debounced search ─────────────────────────────────────────────────────────
const _searchInput = document.getElementById('search-input');
if (_searchInput) {
    let _searchTimer;
    _searchInput.addEventListener('input', () => {
        clearTimeout(_searchTimer);
        _searchTimer = setTimeout(() => {
            document.getElementById('search-form').submit();
        }, 400);
    });
}

function changePerPage(val) {
    const url = new URL(window.location.href);
    url.searchParams.set('per_page', val);
    url.searchParams.set('page', '1');
    window.location.href = url.toString();
}

async function loadPluginCounts() {
  try {
    const data = await apiFetch('/api/system/plugin-counts');
    const run = data.run || {};
    const runTotal = Object.values(run).reduce((a, b) => a + b, 0);
    const set = (id, val) => { const e = document.getElementById(id); if (e) e.textContent = val > 0 ? ` (${val})` : ''; };
    set('fc-run-all', runTotal);
    ['done', 'running', 'pending', 'failed', 'none'].forEach(s => set(`fc-run-${s}`, run[s] || 0));
  } catch (_) {}
}

function escHtml(s) {
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

// ── Task panel ────────────────────────────────────────────────────────────────

async function openTaskPanel() {
  document.getElementById('task-panel-overlay').hidden = false;
  await refreshTaskPanel();
}

function closeTaskPanel() {
  document.getElementById('task-panel-overlay').hidden = true;
}

async function refreshTaskPanel() {
  const body = document.getElementById('task-panel-body');
  if (!body || document.getElementById('task-panel-overlay').hidden) return;
  try {
    const data = await apiFetch('/api/tasks');
    body.innerHTML = renderTaskPanel(data);
  } catch (e) {
    body.innerHTML = `<p class="error-msg">${e.message}</p>`;
  }
}

function renderTaskPanel(data) {
  let html = '';

  html += '<div class="section-title">下载任务</div>';
  if (!data.downloads.length) {
    html += '<p class="muted" style="padding:8px 0">无进行中的下载</p>';
  } else {
    data.downloads.forEach(d => {
      html += `<div class="task-item">
        <span>${escHtml(d.name)}</span>
        <button class="btn btn-xs btn-danger" onclick="cancelDownload(${d.plugin_id})">取消</button>
      </div>`;
    });
  }

  html += '<div class="section-title" style="margin-top:16px">分析队列</div>';
  const allAnalysis = [];
  (data.analysis_current || []).forEach(item => {
    allAnalysis.push({ ...item, _current: true });
  });
  data.analysis_pending.forEach(p => allAnalysis.push(p));

  if (!allAnalysis.length) {
    html += '<p class="muted" style="padding:8px 0">队列为空</p>';
  } else {
    allAnalysis.forEach(item => {
      const tag = item._current
        ? '<span class="badge badge-running" style="margin-right:6px">进行中</span>'
        : '';
      const cancelBtn = item._current ? '' :
        `<button class="btn btn-xs btn-danger" onclick="cancelAnalysis(${item.run_id})">取消</button>`;
      html += `<div class="task-item">${tag}插件 #${item.plugin_id}（Run #${item.run_id}）${cancelBtn}</div>`;
    });
  }
  return html;
}

async function cancelDownload(pluginId) {
  try {
    await apiFetch(`/api/tasks/download/${pluginId}`, 'DELETE');
    showToast('已取消下载', 'success');
    await refreshTaskPanel();
  } catch (e) { showToast('取消失败：' + e.message, 'error'); }
}

async function cancelAnalysis(runId) {
  try {
    await apiFetch(`/api/tasks/analysis/${runId}`, 'DELETE');
    showToast('已从队列移除', 'success');
    await refreshTaskPanel();
    loadPluginCounts();
  } catch (e) { showToast('取消失败：' + e.message, 'error'); }
}

// ── Index page actions ────────────────────────────────────────────────────────

function toggleSelectAll(cb) {
  document.querySelectorAll('.row-check').forEach(c => {
    if (!c.closest('tr').hidden) c.checked = cb.checked;
  });
  onRowCheck();
}

function onRowCheck() {
  const checked = [...document.querySelectorAll('.row-check:checked')]
    .filter(c => !c.closest('tr').hidden);
  const bar = document.getElementById('batch-actions');
  const cnt = document.getElementById('selected-count');
  if (!bar) return;
  bar.style.display = checked.length ? 'flex' : 'none';
  if (cnt) cnt.textContent = checked.length;
}

function clearSelection() {
  document.querySelectorAll('.row-check, #select-all').forEach(c => c.checked = false);
  onRowCheck();
}

function selectedIds() {
  return [...document.querySelectorAll('.row-check:checked')]
    .filter(c => !c.closest('tr').hidden)
    .map(c => Number(c.value));
}

async function analyzeOne(id) {
  try {
    const r = await apiFetch(`/api/plugins/${id}/analyze`, 'POST', {});
    showToast(r.run_id ? `分析已入队 Run #${r.run_id}` : '正在下载后分析…');
    refreshTaskPanel();
  } catch (e) { showToast('分析失败：' + e.message, 'error'); }
}

async function deleteOne(id) {
  if (!confirm('确认删除该插件及所有分析记录？')) return;
  try {
    await apiFetch(`/api/plugins/${id}`, 'DELETE');
    const row = document.getElementById(`row-${id}`);
    if (row) row.remove();
    showToast('已删除', 'success');
  } catch (e) { showToast('删除失败：' + e.message, 'error'); }
}

async function batchAnalyze() {
  const ids = selectedIds();
  if (!ids.length) return;
  try {
    const r = await apiFetch('/api/plugins/analyze-batch', 'POST', { plugin_ids: ids });
    showToast(`${r.run_ids.length} 个分析任务已入队（已分析的已跳过）`);
    clearSelection();
    refreshTaskPanel();
  } catch (e) { showToast('批量分析失败：' + e.message, 'error'); }
}

async function batchReanalyze() {
  const ids = selectedIds();
  if (!ids.length) return;
  if (!confirm(`将重新分析 ${ids.length} 个插件（含已分析），确认？`)) return;
  try {
    const r = await apiFetch('/api/plugins/analyze-batch', 'POST', { plugin_ids: ids, force: true });
    showToast(`${r.run_ids.length} 个重新分析任务已入队`);
    clearSelection();
    refreshTaskPanel();
  } catch (e) { showToast('重新分析失败：' + e.message, 'error'); }
}

async function batchDelete() {
  const ids = selectedIds();
  if (!ids.length) return;
  if (!confirm(`确认删除 ${ids.length} 个插件及所有分析记录？`)) return;
  let ok = 0;
  for (const id of ids) {
    try {
      await apiFetch(`/api/plugins/${id}`, 'DELETE');
      const row = document.getElementById(`row-${id}`);
      if (row) row.remove();
      ok++;
    } catch (_) {}
  }
  showToast(`已删除 ${ok} 个`, 'success');
  clearSelection();
}

function selectFirstN() {
  const input = document.getElementById('select-n-input');
  const n = parseInt(input.value, 10);
  if (!n || n < 1) { showToast('请输入有效的条数', 'error'); return; }

  document.querySelectorAll('.row-check').forEach(cb => cb.checked = false);
  const sa = document.getElementById('select-all');
  if (sa) sa.checked = false;

  const rows = [...document.querySelectorAll('#plugins-table tbody tr')]
    .filter(row => !row.hidden);
  const actual = Math.min(n, rows.length);
  rows.slice(0, actual).forEach(row => {
    const cb = row.querySelector('.row-check');
    if (cb) cb.checked = true;
  });

  onRowCheck();
  if (actual < n) showToast(`仅有 ${actual} 条可见，已全部选中`, 'info');
}

// ── Run log polling ─────────────────────────────────────────────────────────

let _runLogPoller = null;
let _runStatusPoller = null;

function startRunLogPoll(runId) {
  if (_runLogPoller) clearInterval(_runLogPoller);
  let offset = 0;
  const el = document.getElementById('run-log');
  if (!el) return;
  
  _runLogPoller = setInterval(async () => {
    try {
      const data = await apiFetch(`/api/runs/${runId}/logs?since=${offset}`);
      if (data.lines && data.lines.length > 0) {
        const autoScroll = document.getElementById('log-auto-scroll');
        if (!autoScroll || autoScroll.checked) {
          el.textContent += data.lines.join('\n') + (data.lines.length ? '\n' : '');
          el.scrollTop = el.scrollHeight;
        }
        offset = data.total;
      }
      if (data.done) {
        stopRunLogPoll();
        const toast = document.getElementById('analysis-complete-toast');
        if (toast) toast.style.display = 'block';
      }
    } catch (_) {}
  }, 1500);
}

function stopRunLogPoll() {
  clearInterval(_runLogPoller);
  _runLogPoller = null;
}

function startRunStatusPoll(runId) {
  if (_runStatusPoller) clearInterval(_runStatusPoller);
  _runStatusPoller = setInterval(async () => {
    try {
      const data = await apiFetch(`/api/runs/${runId}`);
      if (data.stage_results) updateStageTable(runId, data.stage_results);
      const anyRunning = (data.stage_results || []).some(s => s.status === 'running');
      const allTerminal = (data.stage_results || []).length > 0 &&
        (data.stage_results || []).every(s => s.status === 'done' || s.status === 'failed');
      if (!anyRunning && allTerminal) {
        stopRunStatusPoll();
        stopRunLogPoll();
        const toast = document.getElementById('analysis-complete-toast');
        if (toast) toast.style.display = 'block';
        // Update page status badges
        const headerBadge = document.querySelector('.run-header .badge');
        if (headerBadge && data.run) {
          const labels = {'pending':'队列中','running':'分析中','done':'已完成','failed':'失败'};
          headerBadge.className = `badge badge-${data.run.status}`;
          headerBadge.textContent = labels[data.run.status] || data.run.status;
        }
      }
    } catch (_) {}
  }, 3000);
}

function stopRunStatusPoll() {
  clearInterval(_runStatusPoller);
  _runStatusPoller = null;
}

function updateStageTable(runId, stageResults) {
  stageResults.forEach(sr => {
    const row = document.getElementById(`stage-row-${sr.stage}`);
    if (!row) return;

    const statusCell = row.children[1];
    const durCell = row.children[2];
    const summaryCell = row.children[3];
    const actionCell = row.children[4];

    let statusHtml = '';
    if (sr.status === 'done') {
      statusHtml = '<span class="badge badge-done" style="background:#e8f5e9; color:#2e7d32;">✓ 已完成</span>';
    } else if (sr.status === 'running') {
      statusHtml = '<span class="badge badge-running" style="background:#e3f2fd; color:#1976d2;">⟳ 分析中</span>';
    } else if (sr.status === 'failed') {
      statusHtml = '<span class="badge badge-failed" style="background:#ffebee; color:#c62828;">✗ 失败</span>';
    } else {
      statusHtml = '<span class="badge badge-pending" style="background:#f5f5f5; color:#757575;">待执行</span>';
    }
    if (statusCell) statusCell.innerHTML = statusHtml;

    if (durCell && sr.duration_ms) {
      durCell.textContent = `${Math.floor(sr.duration_ms / 1000)}s`;
    }

    if (summaryCell && sr.result) {
      const stage = sr.stage;
      let summary = '—';
      if (sr.status === 'done') {
        if (stage === 'cloud_services') {
          const topo = sr.result.topology;
          summary = topo === 'pure_edge' ? '边缘计算' : topo === 'centralized' ? '集中式' : topo === 'decentralized' ? '混合式' : topo || '未知';
        } else if (stage === 'payment') {
          summary = (sr.result.payment_required || sr.result.paid || sr.result.has_payment) ? '付费' : '免费';
        } else if (stage === 'license') {
          summary = sr.result.type || sr.result.spdx_id || sr.result.declared_license || '未知';
        } else if (stage === 'mobile_platform') {
          summary = sr.result.label || '未知';
        } else if (stage === 'features') {
          summary = `${(sr.result.feature_list || []).length} 个功能`;
        }
      } else if (sr.status === 'failed') {
        summary = `<span style="color:#c62828; font-size:12px;">${sr.error_msg ? sr.error_msg.slice(0, 20) : '错误'}…</span>`;
      }
      summaryCell.innerHTML = summary;
    }
  });
}

window.addEventListener('beforeunload', () => {
  if (_runLogPoller) clearInterval(_runLogPoller);
  if (_runStatusPoller) clearInterval(_runStatusPoller);
});
