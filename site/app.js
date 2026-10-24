'use strict';
const $ = (id) => document.getElementById(id);
let token = '';
let generation = 0;
$('endpoint').value = location.origin;

function error(message = '') {
  $('error').hidden = !message;
  $('error').textContent = message;
}

async function api(path, body) {
  if (!token) throw new Error('请先输入 ADMIN_TOKEN 并连接实例。');
  const response = await fetch(path, {
    method: body ? 'POST' : 'GET',
    headers: {Authorization: `Bearer ${token}`, ...(body ? {'Content-Type': 'application/json'} : {})},
    body: body ? JSON.stringify(body) : undefined,
    signal: AbortSignal.timeout(35000),
    cache: 'no-store',
  });
  const data = await response.json();
  if (!response.ok) {
    const detail = typeof data.detail === 'string' ? data.detail : '请求格式不正确';
    throw new Error(`${response.status} · ${detail}${response.status === 429 ? '，请稍后重试。' : ''}`);
  }
  return {data, response};
}

function reset() {
  for (const id of ['requests-count', 'success-rate', 'latency', 'cache-hits']) $(id).textContent = '—';
  $('connection-status').textContent = '等待连接';
  $('connection-dot').classList.add('muted');
  $('provider-label').textContent = '尚未读取服务配置';
  $('last-updated').textContent = '未同步';
  $('request-rows').replaceChildren();
  $('response').textContent = '连接你的网关，试着发送一条消息。';
  $('response-meta').textContent = '尚未发送请求';
}

async function refresh() {
  const current = generation;
  const {data} = await api('/api/overview');
  if (current !== generation) return;
  const stats = data.stats;
  $('requests-count').textContent = stats.requests.toLocaleString();
  $('success-rate').textContent = stats.requests ? `${((stats.requests - stats.errors) / stats.requests * 100).toFixed(1)}%` : '—';
  $('latency').textContent = stats.average_latency_ms;
  $('cache-hits').textContent = stats.cache_hits;
  $('cache-description').textContent = `相同请求缓存 ${data.cache_ttl_seconds} 秒`;
  $('quota-label').textContent = `共享限流 ${data.rate_limit_per_minute} 次 / 分钟`;
  $('connection-status').textContent = '网关已连接';
  $('connection-dot').classList.remove('muted');
  $('provider-label').textContent = data.provider === 'mock' ? '本地模拟模型 · 无 API 费用' : 'OpenAI 兼容上游 · 真实 API 调用';
  $('last-updated').textContent = `SYNCED ${new Date().toLocaleTimeString()}`;
  const rows = data.recent_requests.map((r) => {
    const tr = document.createElement('tr');
    const values = [r.id.slice(0, 20) + '…', new Date(r.time * 1000).toLocaleTimeString(), r.provider, r.status, `${r.latency_ms} ms`, r.cached ? 'HIT' : 'MISS', r.served_by];
    values.forEach((value, i) => {
      const td = document.createElement('td');
      if (i === 3) {
        const badge = document.createElement('span');
        badge.className = `status-code${r.status >= 400 ? ' failed' : ''}`;
        badge.textContent = value;
        td.append(badge);
      } else td.textContent = value;
      tr.append(td);
    });
    return tr;
  });
  $('request-rows').replaceChildren(...rows);
  if (!rows.length) {
    const td = document.createElement('td');
    td.colSpan = 7; td.className = 'empty'; td.textContent = '暂无请求。发送一条消息，开始验证网关。';
    const tr = document.createElement('tr'); tr.append(td); $('request-rows').append(tr);
  }
}

async function safeRefresh() {
  const current = generation;
  error();
  try { await refresh(); } catch (e) {
    if (current !== generation) return;
    $('connection-status').textContent = '连接失败';
    $('connection-dot').classList.add('muted');
    error(e.message);
  }
}

$('connection-form').addEventListener('submit', async (e) => {
  e.preventDefault(); generation++; reset(); token = $('token').value.trim();
  await safeRefresh();
});
$('disconnect').addEventListener('click', () => {
  generation++; token = ''; $('token').value = ''; reset(); error();
});
$('refresh').addEventListener('click', safeRefresh);
$('prompt-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  const current = generation;
  $('send').disabled = true; $('response-meta').textContent = '请求中…'; error();
  try {
    const {data, response} = await api('/api/playground', {model: 'gateway-default', messages: [{role: 'user', content: $('prompt').value}]});
    if (current !== generation) return;
    $('response').textContent = data.choices[0].message.content;
    $('response-meta').textContent = `200 OK · CACHE ${response.headers.get('X-Cache')}`;
    await refresh();
  } catch (e) {
    if (current === generation) { $('response-meta').textContent = '请求失败'; error(e.message); }
  } finally { $('send').disabled = false; }
});
