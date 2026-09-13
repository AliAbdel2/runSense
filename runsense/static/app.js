(function () {
  'use strict';

  const state = { plan: null, speaking: false, mode: 'demo', strava: null, integrations: [], expiryTimer: null };
  const $ = (selector) => document.querySelector(selector);
  const $$ = (selector) => Array.from(document.querySelectorAll(selector));

  function escapeHtml(value) {
    return String(value == null ? '' : value).replace(/[&<>'"]/g, (char) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' }[char]));
  }

  function announce(message) { $('#announcer').textContent = message || ''; }
  function showError(message) { $('#error-message').textContent = message; $('#error-banner').hidden = false; announce(message); }
  function clearError() { $('#error-banner').hidden = true; }
  function valueOr(value, fallback) { return value === undefined || value === null || value === '' ? fallback : value; }

  function formatDate(value, options) {
    if (!value) return '—';
    const date = new Date(`${value}T12:00:00`);
    if (Number.isNaN(date.getTime())) return escapeHtml(value);
    return date.toLocaleDateString(undefined, options || { weekday: 'long', month: 'long', day: 'numeric' });
  }

  function formatKm(km) { return km === undefined || km === null ? '—' : `${km} km`; }

  function humanStatus(value) {
    const raw = String(value == null ? '' : value);
    const labels = {
      accepted: 'Guide confirmed (demo)',
      declined: 'Guide declined',
      pending: 'No guide confirmed',
      not_required: 'No guide needed',
      not_connected: 'Not connected',
      configured_unverified: 'Configured · unverified',
      connected: 'Connected',
      access_denied: 'Access denied',
      error: 'Connection error',
      demo: 'Demo'
    };
    if (labels[raw.toLowerCase()]) return labels[raw.toLowerCase()];
    return raw.replace(/_/g, ' ').replace(/\b\w/g, (letter) => letter.toUpperCase()) || 'Status unavailable';
  }

  function sessionLabel(session) {
    const kind = String(valueOr(session.kind, 'Run')).toLowerCase();
    if (kind === 'rest' || kind === 'recovery') return 'Recovery day';
    if (kind === 'intervals') return 'Intervals';
    if (kind === 'long') return 'Long run';
    if (kind === 'easy') return 'Easy run';
    return humanStatus(valueOr(session.kind, 'Run'));
  }

  function setMode(response) {
    if (state.expiryTimer) clearTimeout(state.expiryTimer);
    const preview = response && (response.mode === 'strava_preview' || response.source === 'strava_mcp');
    state.mode = preview ? 'strava_preview' : 'demo';
    $('#mode-label').textContent = preview ? 'Personal preview · stored only for this session' : 'Demo mode';
    $('#mode-badge').setAttribute('title', preview ? 'Personal preview · stored only for this session' : 'Synthetic demo data');
    if (preview) {
      state.expiryTimer = setTimeout(() => {
        state.plan = null;
        if ('speechSynthesis' in window) window.speechSynthesis.cancel();
        $('#strava-detail').textContent = 'Personal preview expired and cleared. Read Strava again for a fresh plan.';
        loadDemo();
      }, Math.min(response.expires_in_seconds || 3600, 3600) * 1000);
    }
  }

  function stravaStatusLabel(status) {
    return humanStatus(status).replace(' (demo)', '');
  }

  function renderPlan(response) {
    const plan = response && response.plan;
    if (!plan) { showError('The API returned no plan to display.'); return; }
    setMode(response);
    state.plan = plan;
    const athleteName = valueOr(plan.athlete_name, 'Sara');
    const goal = valueOr(plan.goal, 'A comfortable, consistent 5K');
    const possessive = String(athleteName).toLowerCase() === 'you' ? 'your' : `${athleteName}'s`;
    $('#athlete-name').textContent = athleteName;
    $('#athlete-goal').textContent = String(goal).replace(/^A /, '').replace(/, consistent/, '') || '5K goal';
    $('#athlete-chip').setAttribute('aria-label', `Athlete ${athleteName}, goal ${goal}`);
    $('#athlete-avatar').textContent = String(athleteName).slice(0, 1).toUpperCase();
    $('#athlete-avatar').setAttribute('aria-label', `Athlete ${athleteName}`);
    $('#page-subtitle').textContent = `A calm, consistent plan for ${possessive} comfortable 5K.`;
    clearError();
    const sessions = Array.isArray(plan.sessions) ? plan.sessions : [];
    const next = sessions.find((session) => !/rest|recovery/i.test(String(session.kind || ''))) || sessions[0];
    $('#week-start-label').textContent = formatDate(plan.week_start, { month: 'short', day: 'numeric', year: 'numeric' });
    $('#week-total-km').textContent = valueOr(plan.week_km, '—');
    $('#coach-rationale').textContent = valueOr(plan.rationale, 'The plan rationale is not available.');
    if (next) {
      $('#hero-date').textContent = formatDate(next.date);
      $('#next-workout-title').textContent = `${sessionLabel(next)} · ${formatKm(next.km)}`;
      $('#hero-meta').textContent = `${valueOr(next.venue, 'Venue not specified')} · ${humanStatus(valueOr(next.guide_status, ''))}`;
      $('#hero-rationale').textContent = valueOr(next.rationale, valueOr(next.spoken_summary, ''));
      $('#hero-status').textContent = humanStatus(valueOr(next.guide_status, 'planned'));
      $('#hero-status').className = `status-pill ${/cancel|declined|pending|off|miss/i.test(String(next.guide_status || '')) ? 'changed' : 'planned'}`;
    } else {
      $('#hero-date').textContent = 'No session scheduled';
      $('#next-workout-title').textContent = 'Your next workout will appear here.';
      $('#hero-meta').textContent = 'No session data was returned.';
      $('#hero-rationale').textContent = '';
    }
    renderWeek(sessions);
    renderTrace(response.trace);
    announce(`Plan ready for ${valueOr(plan.athlete_name, 'the athlete')}.`);
  }

  function renderWeek(sessions) {
    const list = $('#week-list');
    list.setAttribute('aria-busy', 'false');
    if (!sessions.length) { list.innerHTML = '<p class="empty-state">No sessions were returned for this week.</p>'; return; }
    list.innerHTML = sessions.map((session, index) => {
      const rest = /rest|recovery/i.test(String(session.kind || ''));
      const rawStatus = valueOr(session.guide_status, '');
      const status = humanStatus(rawStatus);
      const statusOff = /off|none|cancel|unavailable|declined|pending|not connected/i.test(String(status));
      const date = session.date ? new Date(`${session.date}T12:00:00`) : null;
      const weekday = date && !Number.isNaN(date.getTime()) ? date.toLocaleDateString(undefined, { weekday: 'short' }) : 'Day';
      const day = date && !Number.isNaN(date.getTime()) ? date.toLocaleDateString(undefined, { day: 'numeric' }) : '—';
      const reason = valueOr(session.rationale, valueOr(session.spoken_summary, ''));
      return `<article class="week-row ${rest ? 'rest-row' : ''} ${index === 0 ? 'today' : ''}">
        <div class="day-label"><strong>${escapeHtml(weekday)}</strong>${escapeHtml(day)}</div>
        <div class="session-kind">${escapeHtml(sessionLabel(session))}</div>
        <div class="session-km">${escapeHtml(formatKm(session.km))}</div>
        <div class="session-venue">${escapeHtml(valueOr(session.venue, 'Venue not specified'))}</div>
        <div class="guide-status ${statusOff ? 'off' : ''}"><span aria-hidden="true"></span>${escapeHtml(status)}</div>
        ${reason ? `<div class="session-reason"><span class="reason-label">Why: </span>${escapeHtml(reason)}</div>` : ''}
      </article>`;
    }).join('');
  }

  function renderTrace(trace) {
    const list = $('#trace-list');
    if (!Array.isArray(trace) || !trace.length) { list.innerHTML = '<p class="empty-state">No trace details were returned.</p>'; return; }
    list.innerHTML = trace.map((item) => {
      const status = String(valueOr(item.status, '')).toLowerCase();
      const passed = ['success', 'ok', 'completed', 'verified'].includes(status);
      const attempt = item.attempt == null ? '' : `Attempt ${escapeHtml(item.attempt)}`;
      const latency = item.latency_ms == null ? '' : `${escapeHtml(item.latency_ms)} ms`;
      return `<div class="trace-item ${passed ? '' : 'pending'}"><span class="trace-node" aria-hidden="true"></span><div><span class="trace-name">${escapeHtml(valueOr(item.name, valueOr(item.tool, 'Planner step')))}</span><span class="trace-detail">${escapeHtml(valueOr(item.detail, 'No detail returned.'))}</span></div><span class="trace-meta">${attempt}${attempt && latency ? ' · ' : ''}${latency}</span></div>`;
    }).join('');
  }

  function renderIntegrations(data) {
    const integrations = data && Array.isArray(data.integrations) ? data.integrations.slice() : [];
    if (!integrations.some((item) => /strava/i.test(String(item.name || '')))) {
      const strava = state.strava || {};
      integrations.push({ name: 'Strava MCP', status: valueOr(strava.status, 'not_connected'), detail: valueOr(strava.detail, 'Connect from server configuration.') });
    }
    state.integrations = integrations;
    const list = $('#integrations-list');
    if (!integrations.length) { list.innerHTML = '<p class="empty-state">No integration details returned.</p>'; return; }
    list.innerHTML = integrations.map((item) => {
      const name = valueOr(item.name, 'Integration');
      const short = name.split(/\s+/).map((part) => part[0]).join('').slice(0, 2).toUpperCase();
      const status = valueOr(item.status, 'demo');
      const detail = valueOr(item.detail, 'Demo connection; no live request made.');
      const ready = ['connected', 'ready'].includes(String(status).toLowerCase());
      return `<div class="integration-item"><span class="integration-name"><span class="integration-icon" aria-hidden="true">${escapeHtml(short)}</span>${escapeHtml(name)}</span><span class="integration-state ${ready ? 'ready' : ''}" title="${escapeHtml(detail)}">${escapeHtml(humanStatus(status))}</span></div>`;
    }).join('');
    updateConnectionLabel();
  }

  function updateConnectionLabel() {
    const connected = state.integrations.filter((item) => ['connected', 'ready'].includes(String(item.status || '').toLowerCase())).length;
    const stravaConnected = stravaReady();
    $('#connection-text').textContent = stravaConnected ? `Strava MCP connected${connected > 1 ? ` · ${connected} apps connected` : ''}` : connected ? `${connected} app${connected === 1 ? '' : 's'} connected` : 'No apps connected';
    $('#connection-label').classList.toggle('is-connected', stravaConnected || connected > 0);
  }

  function renderEvaluation(data) {
    const panel = $('#evaluation-panel');
    if (!data) { panel.innerHTML = '<p class="empty-state">No evaluation result returned. Perception: not measured.</p>'; return; }
    const passed = data.passed === true || (typeof data.passed === 'number' && data.total > 0 && data.passed === data.total);
    const results = Array.isArray(data.results) ? data.results : [];
    const total = valueOr(data.total, results.length);
    const countPassed = results.filter((result) => result.passed === true).length;
    const perception = data.perception || { status: 'not_measured', detail: 'No perception measurement was made.' };
    panel.innerHTML = `<div class="evaluation-summary ${passed ? '' : 'fail'}"><span aria-hidden="true">${passed ? '✓' : '!'}</span>${passed ? 'Reliability checks passed' : 'Reliability checks need attention'} <span>(${countPassed}/${escapeHtml(total)})</span></div>${results.length ? `<div class="evaluation-checks">${results.map((result) => `<div class="check-item ${result.passed === true ? '' : 'fail'}">${escapeHtml(valueOr(result.name, 'Check'))}: ${escapeHtml(valueOr(result.detail, result.passed === true ? 'Passed' : 'Needs attention'))}</div>`).join('')}</div>` : ''}<p class="empty-state">Perception: ${escapeHtml(valueOr(perception.status, 'not measured'))} · ${escapeHtml(valueOr(perception.detail, 'No perception measurement was made.'))}</p>`;
  }

  async function request(url, options) {
    const response = await fetch(url, { headers: { 'Content-Type': 'application/json' }, ...options });
    let payload;
    try { payload = await response.json(); } catch (_) { payload = null; }
    if (!response.ok) throw new Error(payload && (payload.detail || payload.message) || `Request failed (${response.status})`);
    return payload;
  }

  function stravaReady() {
    return !!(state.strava && state.strava.status === 'connected' && state.strava.tool_configured === true);
  }

  function updateStravaPlanButton() {
    const button = $('#strava-plan');
    if (button) button.disabled = !stravaReady();
  }

  function setActionBusy(busy, message) {
    $$('.action-button[data-scenario]').forEach((button) => { button.disabled = busy; button.setAttribute('aria-busy', String(busy)); });
    const stravaButton = $('#strava-plan');
    if (stravaButton) { stravaButton.disabled = busy || !stravaReady(); stravaButton.setAttribute('aria-busy', String(busy)); }
    $('#action-status').textContent = message || '';
  }

  async function loadDemo() {
    $('#week-list').setAttribute('aria-busy', 'true');
    try { renderPlan(await request('/api/demo')); } catch (error) { $('#week-list').setAttribute('aria-busy', 'false'); showError(`Could not load the demo plan: ${error.message}`); $('#next-workout-title').textContent = 'Plan unavailable'; $('#hero-meta').textContent = 'Check the API and try again.'; }
  }

  async function loadStatus() {
    try { renderIntegrations(await request('/api/status')); } catch (_) { renderIntegrations({ integrations: [{ name: 'Google Sheets', status: 'demo' }, { name: 'Google Calendar', status: 'demo' }, { name: 'Notion', status: 'demo' }, { name: 'ElevenLabs', status: 'optional' }] }); }
  }

  function renderStravaStatus(data, message) {
    const status = valueOr(data && data.status, 'not_connected');
    state.strava = data || { status };
    const connected = status === 'connected' && data && data.tool_configured === true;
    $('#strava-status-pill').textContent = stravaStatusLabel(status);
    $('#strava-status-pill').className = `strava-status-pill ${connected ? 'is-connected' : status === 'error' || status === 'access_denied' ? 'is-error' : ''}`;
    $('#strava-detail').textContent = message || valueOr(data && data.detail, status === 'not_connected' ? 'Not connected. Server controlled configuration is required.' : 'Strava MCP status updated.');
    const tools = data && Array.isArray(data.tools) ? data.tools : [];
    $('#strava-tools').innerHTML = tools.map((tool) => {
      const name = valueOr(tool && tool.name, 'Unnamed activity tool');
      const description = valueOr(tool && tool.description, 'No description provided.');
      const schema = tool && (tool.input_schema || tool.inputSchema || tool.schema);
      let schemaText = '';
      if (schema) {
        try { schemaText = `<pre class="strava-schema">${escapeHtml(JSON.stringify(schema, null, 2))}</pre>`; } catch (_) { schemaText = ''; }
      }
      return `<details class="strava-tool"><summary>${escapeHtml(name)}</summary><p>${escapeHtml(description)}</p>${schemaText}</details>`;
    }).join('');
    updateStravaPlanButton();
    const integrations = state.integrations.length ? state.integrations.map((item) => /strava/i.test(String(item.name || '')) ? { ...item, status, detail: valueOr(data && data.detail, item.detail) } : item) : [{ name: 'Strava MCP', status, detail: valueOr(data && data.detail, '') }];
    renderIntegrations({ integrations });
    updateConnectionLabel();
    announce(`Strava MCP: ${stravaStatusLabel(status)}.`);
  }

  async function loadStravaStatus() {
    try { renderStravaStatus(await request('/api/strava/status')); }
    catch (error) { renderStravaStatus({ status: 'error', detail: error.message, tool_configured: false }, `Could not check Strava MCP: ${error.message}`); }
  }

  async function clearRejectedPersonalPreview() {
    if (state.mode !== 'strava_preview') return;
    state.plan = null;
    if ('speechSynthesis' in window) window.speechSynthesis.cancel();
    setMode({ mode: 'demo' });
    await loadDemo();
    announce('Personal preview cleared. The screen now shows synthetic demo data.');
  }

  async function checkStrava() {
    const button = $('#strava-check');
    button.disabled = true;
    $('#strava-detail').textContent = 'Checking the configured Strava MCP connection…';
    try {
      const status = await request('/api/strava/check', { method: 'POST' });
      renderStravaStatus(status);
      if (status.status !== 'connected') await clearRejectedPersonalPreview();
    }
    catch (error) { renderStravaStatus({ status: 'error', detail: error.message, tool_configured: false }, `Could not check Strava MCP: ${error.message}`); }
    button.disabled = false;
  }

  async function disconnectStrava() {
    const button = $('#strava-disconnect');
    button.disabled = true;
    try {
      const response = await request('/api/strava/disconnect', { method: 'POST' });
      if ('speechSynthesis' in window) window.speechSynthesis.cancel();
      state.plan = null;
      setMode({ mode: 'demo' });
      renderStravaStatus(response, 'Disconnected locally. Any Strava preview was cleared from this session.');
      await loadDemo();
    } catch (error) {
      $('#strava-detail').textContent = `Could not disconnect locally: ${error.message}`;
      announce(`Could not disconnect Strava MCP: ${error.message}`);
    }
    button.disabled = false;
  }

  async function planWithStrava() {
    const status = state.strava || {};
    if (status.status !== 'connected' || status.tool_configured !== true) {
      $('#strava-detail').textContent = 'Connect Strava MCP and select an activity tool before planning.';
      announce('Strava MCP is not ready for planning.');
      return;
    }
    const button = $('#strava-plan');
    setActionBusy(true, 'Reading personal Strava history…');
    $('#strava-check').disabled = true;
    $('#strava-disconnect').disabled = true;
    $('#strava-detail').textContent = 'Reading your configured Strava activity tool…';
    clearError();
    try {
      const response = await request('/api/plan', { method: 'POST', body: JSON.stringify({ source: 'strava_mcp', scenario: 'baseline', use_llm: false }) });
      renderPlan(response);
      $('#strava-detail').textContent = 'Personal preview ready · stored only for this session.';
      announce('Personal Strava preview ready.');
    } catch (error) {
      await clearRejectedPersonalPreview();
      await loadStravaStatus();
      $('#strava-detail').textContent = `Could not plan with Strava MCP: ${error.message}`;
      showError(`Could not plan with Strava MCP: ${error.message}`);
    }
    setActionBusy(false, '');
    $('#strava-check').disabled = false;
    $('#strava-disconnect').disabled = false;
  }

  async function planScenario(scenario, label) {
    setActionBusy(true, `${label}…`); clearError();
    try { const response = await request('/api/plan', { method: 'POST', body: JSON.stringify({ scenario, use_llm: false }) }); renderPlan(response); setActionBusy(false, `Demo preview: ${label} complete. Strava plans stay unchanged.`); announce(`Demo preview: ${label} complete. Strava plans stay unchanged.`); }
    catch (error) { setActionBusy(false, ''); showError(`Could not run ${label.toLowerCase()}: ${error.message}`); }
  }

  async function evaluate() {
    const button = $('#evaluate-button'); button.disabled = true; button.setAttribute('aria-busy', 'true'); button.textContent = 'Checking…'; clearError();
    try { renderEvaluation(await request('/api/evaluate', { method: 'POST' })); announce('Reliability checks complete.'); }
    catch (error) { showError(`Could not run reliability checks: ${error.message}`); }
    button.disabled = false; button.removeAttribute('aria-busy'); button.textContent = 'Run reliability checks';
  }

  function toggleSpeech() {
    const button = $('#listen-button');
    if (!('speechSynthesis' in window) || !('SpeechSynthesisUtterance' in window)) { showError('Read aloud is not supported in this browser.'); return; }
    if (state.speaking) { window.speechSynthesis.cancel(); state.speaking = false; button.classList.remove('is-speaking'); button.setAttribute('aria-pressed', 'false'); $('#listen-label').textContent = 'Listen to plan'; announce('Stopped reading the plan.'); return; }
    const plan = state.plan; const next = plan && Array.isArray(plan.sessions) ? plan.sessions.find((session) => !/rest|recovery/i.test(String(session.kind || ''))) || plan.sessions[0] : null;
    if (!next) { showError('There is no workout summary to read yet.'); return; }
    const text = [plan.athlete_name, plan.rationale, ...plan.sessions.map((session) => `${formatDate(session.date)}. ${session.spoken_summary || session.rationale}`)].filter(Boolean).join('. ');
    const utterance = new SpeechSynthesisUtterance(text); utterance.rate = .95; utterance.onend = () => { state.speaking = false; button.classList.remove('is-speaking'); button.setAttribute('aria-pressed', 'false'); $('#listen-label').textContent = 'Listen to plan'; announce('Finished reading the plan.'); }; utterance.onerror = utterance.onend;
    window.speechSynthesis.cancel(); window.speechSynthesis.speak(utterance); state.speaking = true; button.classList.add('is-speaking'); button.setAttribute('aria-pressed', 'true'); $('#listen-label').textContent = 'Stop reading'; announce('Reading the week plan aloud.');
  }

  function init() {
    $('#today-label').textContent = new Date().toLocaleDateString(undefined, { weekday: 'long', month: 'long', day: 'numeric', year: 'numeric' });
    $('#dismiss-error').addEventListener('click', clearError);
    $('#listen-button').addEventListener('click', toggleSpeech);
    $('#evaluate-button').addEventListener('click', evaluate);
    $('#strava-check').addEventListener('click', checkStrava);
    $('#strava-disconnect').addEventListener('click', disconnectStrava);
    $('#strava-plan').addEventListener('click', planWithStrava);
    $$('.action-button[data-scenario]').forEach((button) => button.addEventListener('click', () => planScenario(button.dataset.scenario, button.textContent.replace('→', '').trim())));
    loadDemo();
    loadStatus();
    loadStravaStatus();
  }

  document.addEventListener('DOMContentLoaded', init);
}());
