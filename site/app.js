'use strict';
const $ = (id) => document.getElementById(id);
const sourceNames = {web: '网站', app: 'App', api: 'API'};
let token = '';
let generation = 0;
let connected = false;
let sending = false;
let refreshing = null;
let pollTimer = null;
let countdownTimer = null;
let retryAt = 0;
const controllers = new Set();
$('endpoint').value = location.origin;

class ApiError extends Error {
  constructor(message, status = 0, retryAfter = 0, requestId = '') {
    super(message);
    Object.assign(this, {status, retryAfter, requestId});
  }
}

function showError(message = '', target = 'error') {
  $(target).hidden = !message;
  $(target).textContent = message;
}

function failureMessage(status) {
  return ({
    401: '管理令牌无效或已失效。请使用 ADMIN_TOKEN 重新连接，调用令牌 GATEWAY_TOKEN 不能用于管理台。',
    413: '消息过长，请缩短内容后重试。',
    422: '请求内容不符合要求，请检查消息是否为空或过长。',
    429: '已达到共享调用限额。倒计时结束后可手动重试，不会自动重发消息。',
    502: '模型上游暂时不可用。请检查服务端的上游配置，稍后再试。',
    503: '网关暂未就绪，请检查后端和 Redis。恢复后将继续同步。',
  })[status] || `服务返回 ${status}，请稍后重试或检查网关日志。`;
}

async function api(path, body) {
  if (!token) throw new ApiError('请先在连接设置中输入 ADMIN_TOKEN。');
  const controller = new AbortController();
  controllers.add(controller);
  let timedOut = false;
  const timer = setTimeout(() => { timedOut = true; controller.abort(); }, 35000);
  try {
    const response = await fetch(path, {
      method: body ? 'POST' : 'GET',
      headers: {Authorization: `Bearer ${token}`, ...(body ? {'Content-Type': 'application/json'} : {})},
      body: body ? JSON.stringify(body) : undefined,
      signal: controller.signal,
      cache: 'no-store',
    });
    const requestId = response.headers.get('X-Request-ID') || '';
    if (!response.ok) {
      const seconds = Number(response.headers.get('Retry-After'));
      throw new ApiError(failureMessage(response.status), response.status,
        response.status === 429 ? Math.min(3600, Math.max(1, Number.isFinite(seconds) && seconds > 0 ? seconds : 60)) : 0,
        requestId);
    }
    let data;
    try { data = await response.json(); } catch {
      throw new ApiError('服务未返回有效的 JSON 数据，请确认连接的是 ModelJetty 网关。');
    }
    return {data, response};
  } catch (e) {
    if (e instanceof ApiError) throw e;
    if (timedOut) throw new ApiError('连接超时，请检查网关地址和网络，稍后重试。');
    if (e.name === 'AbortError') throw e;
    throw new ApiError('无法连接网关，请检查网络、后端进程和服务地址。');
  } finally {
    clearTimeout(timer); controllers.delete(controller);
  }
}

function displayFailure(e) {
  return e.message + (e.requestId ? `\n请求 ID：${e.requestId}` : '');
}

function updateSend() {
  const remaining = Math.max(0, Math.ceil((retryAt - Date.now()) / 1000));
  $('send').disabled = !connected || sending || remaining > 0;
  $('send').textContent = sending ? '发送中…' : remaining ? `${remaining} 秒后可重试` : '发送请求 ↗';
  clearInterval(countdownTimer);
  if (remaining && !document.hidden) countdownTimer = setInterval(updateSend, 1000);
}

function updateGuide(id, done) {
  $(id).classList.toggle('done', done);
  $(id).querySelector('small').textContent = done ? '已完成' : '待完成';
}

function schedulePoll() {
  clearTimeout(pollTimer);
  if (!connected || !$('auto-sync').checked || document.hidden) return;
  pollTimer = setTimeout(() => safeRefresh(true), 5000);
}

function syncLabel() {
  $('sync-state').textContent = !connected ? '连接后自动同步' : document.hidden ? '后台已暂停' : $('auto-sync').checked ? '每 5 秒同步' : '自动同步已暂停';
}

function reset() {
  connected = false; retryAt = 0; sending = false;
  clearTimeout(pollTimer); clearInterval(countdownTimer);
  for (const controller of controllers) controller.abort();
  for (const id of ['requests-count', 'success-rate', 'latency', 'cache-hits']) $(id).textContent = '—';
  $('connection-status').textContent = '等待连接';
  $('connection-dot').classList.add('muted');
  $('provider-label').textContent = '尚未读取服务配置';
  $('quota-label').textContent = '先连接实例，再发送消息';
  $('cache-description').textContent = '基于相同请求内容';
  $('last-updated').textContent = '未同步';
  $('request-rows').replaceChildren(emptyRow('连接实例后，发送第一条消息；网站与 App 的记录会在这里同步。'));
  $('response').textContent = '连接你的网关，试着发送一条消息。';
  $('response-meta').textContent = '尚未发送请求';
  $('response-id').textContent = '';
  for (const id of ['guide-connect', 'guide-send', 'guide-linked']) updateGuide(id, false);
  showError(); showError('', 'playground-error'); updateSend(); syncLabel();
}

function emptyRow(message) {
  const td = document.createElement('td'); td.colSpan = 8; td.className = 'empty'; td.textContent = message;
  const tr = document.createElement('tr'); tr.append(td); return tr;
}

async function refresh() {
  const current = generation;
  if (refreshing?.generation === current) return refreshing.promise;
  const task = {generation: current};
  refreshing = task;
  task.promise = (async () => {
    const {data} = await api('/api/overview');
    if (current !== generation) return;
    if (!data.stats || !Array.isArray(data.recent_requests)) throw new ApiError('实例返回的数据不完整，请确认 ModelJetty 服务版本。');
    connected = true;
    const stats = data.stats;
    $('requests-count').textContent = stats.requests.toLocaleString();
    $('success-rate').textContent = stats.requests ? `${((stats.requests - stats.errors) / stats.requests * 100).toFixed(1)}%` : '—';
    $('latency').textContent = stats.average_latency_ms;
    $('cache-hits').textContent = stats.cache_hits;
    $('cache-description').textContent = data.cache_ttl_seconds ? `相同请求缓存 ${data.cache_ttl_seconds} 秒` : '响应缓存已关闭';
    $('quota-label').textContent = `共享限流 ${data.rate_limit_per_minute} 次 / 分钟`;
    $('connection-status').textContent = '网关已连接';
    $('connection-dot').classList.remove('muted');
    $('provider-label').textContent = data.provider === 'mock' ? '本地模拟模型 · 无 API 费用' : '真实上游 · 会产生供应商 API 费用';
    $('last-updated').textContent = `最近同步 ${new Date().toLocaleTimeString()}`;
    updateGuide('guide-connect', true);
    updateGuide('guide-linked', new Set(data.recent_requests.map(r => r.source).filter(Boolean)).size >= 2);
    const expanded = new Set([...document.querySelectorAll('#request-rows details[open]')].map(el => el.dataset.requestId));
    const rows = data.recent_requests.map((r) => {
      const tr = document.createElement('tr');
      const idCell = document.createElement('td');
      const details = document.createElement('details');
      details.dataset.requestId = r.id; details.open = expanded.has(r.id);
      const summary = document.createElement('summary'); summary.textContent = `${r.id.slice(0, 20)}…`;
      const fullId = document.createElement('code'); fullId.textContent = r.id;
      details.append(summary, fullId); idCell.append(details); tr.append(idCell);
      const values = [new Date(r.time * 1000).toLocaleTimeString(), sourceNames[r.source] || '未标记', r.provider, r.status, `${r.latency_ms} ms`, r.cached ? 'HIT' : 'MISS', r.served_by];
      values.forEach((value, i) => {
        const td = document.createElement('td');
        if (i === 3) {
          const badge = document.createElement('span'); badge.className = `status-code${r.status >= 400 ? ' failed' : ''}`;
          badge.textContent = value; td.append(badge);
        } else td.textContent = value;
        tr.append(td);
      });
      return tr;
    });
    $('request-rows').replaceChildren(...(rows.length ? rows : [emptyRow('暂无请求。去试验台发送一条消息，开始验证完整链路。')]));
    showError(); updateSend(); syncLabel();
  })();
  try { await task.promise; } finally { if (refreshing === task) refreshing = null; }
}

async function safeRefresh(background = false) {
  const current = generation;
  if (background && (sending || refreshing)) { schedulePoll(); return; }
  $('refresh').disabled = true;
  try { await refresh(); } catch (e) {
    if (current !== generation) return;
    if (e.status === 401) {
      connected = false; updateSend(); syncLabel();
    }
    $('connection-status').textContent = connected ? '同步中断 · 当前为上次数据' : '连接失败';
    $('connection-dot').classList.add('muted');
    showError(displayFailure(e));
  } finally {
    if (current === generation) { $('refresh').disabled = false; schedulePoll(); }
  }
}

$('connection-form').addEventListener('submit', async (e) => {
  e.preventDefault(); generation++; reset(); token = $('token').value.trim();
  await safeRefresh();
});
$('disconnect').addEventListener('click', () => {
  generation++; token = ''; $('token').value = ''; reset(); $('refresh').disabled = false;
});
$('refresh').addEventListener('click', () => safeRefresh());
$('auto-sync').addEventListener('change', () => { syncLabel(); schedulePoll(); });

document.addEventListener('visibilitychange', () => {
  syncLabel(); updateSend();
  if (document.hidden) clearTimeout(pollTimer);
  else if (connected && $('auto-sync').checked) safeRefresh(true);
});

$('prompt-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  if (!connected || sending || retryAt > Date.now()) return;
  const current = generation;
  sending = true; updateSend(); $('response-meta').textContent = '请求中…'; showError('', 'playground-error');
  try {
    const {data, response} = await api('/api/playground', {model: 'gateway-default', messages: [{role: 'user', content: $('prompt').value}]});
    if (current !== generation) return;
    const content = data?.choices?.[0]?.message?.content;
    if (typeof content !== 'string') throw new ApiError('模型回复格式不正确，请检查网关和上游配置。');
    $('response').textContent = content;
    $('response-meta').textContent = `200 OK · CACHE ${response.headers.get('X-Cache')}`;
    $('response-id').textContent = `请求 ID：${response.headers.get('X-Request-ID') || data.id || '未提供'}`;
    updateGuide('guide-send', true);
    await safeRefresh();
  } catch (e) {
    if (current === generation) {
      $('response-meta').textContent = '请求失败 · 可修改后重试';
      if (e.status === 429) retryAt = Date.now() + e.retryAfter * 1000;
      if (e.status === 401) { connected = false; clearTimeout(pollTimer); syncLabel(); }
      showError(displayFailure(e), 'playground-error');
    }
  } finally {
    if (current === generation) { sending = false; updateSend(); schedulePoll(); }
  }
});
updateSend();
