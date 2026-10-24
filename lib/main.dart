import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;

import 'gateway_api.dart';

void main() => runApp(const HarborApp());

class HarborApp extends StatelessWidget {
  const HarborApp({super.key, this.client});
  final http.Client? client;
  @override
  Widget build(BuildContext context) => MaterialApp(
    title: 'Harbor · AI Gateway',
    debugShowCheckedModeBanner: false,
    theme: ThemeData(
      useMaterial3: true,
      colorScheme: ColorScheme.fromSeed(seedColor: const Color(0xFF087E68)),
      scaffoldBackgroundColor: const Color(0xFFF5F6F8),
      inputDecorationTheme: const InputDecorationTheme(
        border: OutlineInputBorder(),
        filled: true,
        fillColor: Colors.white,
      ),
    ),
    home: GatewayScreen(client: client),
  );
}

class GatewayScreen extends StatefulWidget {
  const GatewayScreen({super.key, this.client});
  final http.Client? client;
  @override
  State<GatewayScreen> createState() => _GatewayScreenState();
}

class _GatewayScreenState extends State<GatewayScreen> {
  final _endpoint = TextEditingController(text: 'http://localhost:8000');
  final _token = TextEditingController();
  final _prompt = TextEditingController(text: '用三句话解释 Kubernetes 的 Service。');
  late final http.Client _client;
  GatewayApi? _api;
  Map<String, dynamic>? _overview;
  String? _error;
  String _reply = '连接网关后发送请求。默认模拟模式不调用真实模型。';
  String _replyMeta = '';
  bool _busy = false;
  int _tab = 0;
  int _generation = 0;

  @override
  void initState() {
    super.initState();
    _client = widget.client ?? http.Client();
  }

  @override
  void dispose() {
    _endpoint.dispose();
    _token.dispose();
    _prompt.dispose();
    if (widget.client == null) _client.close();
    super.dispose();
  }

  Future<void> _connect() async {
    final attempt = ++_generation;
    setState(() {
      _busy = true;
      _error = null;
      _overview = null;
      _api = null;
    });
    try {
      final api = GatewayApi(
        _endpoint.text.trim(),
        _token.text.trim(),
        _client,
      );
      final overview = await api.overview();
      if (!mounted || attempt != _generation) return;
      setState(() {
        _api = api;
        _overview = overview;
        _tab = 0;
      });
    } catch (e) {
      if (mounted && attempt == _generation) {
        setState(() => _error = e.toString());
      }
    } finally {
      if (mounted && attempt == _generation) setState(() => _busy = false);
    }
  }

  Future<void> _refresh() async {
    final api = _api;
    final attempt = _generation;
    if (api == null) return;
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      final overview = await api.overview();
      if (mounted && attempt == _generation) {
        setState(() => _overview = overview);
      }
    } catch (e) {
      if (mounted && attempt == _generation) {
        setState(() => _error = e.toString());
      }
    } finally {
      if (mounted && attempt == _generation) setState(() => _busy = false);
    }
  }

  Future<void> _send() async {
    final api = _api;
    if (api == null || _prompt.text.trim().isEmpty) return;
    final attempt = _generation;
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      final result = await api.send(_prompt.text.trim());
      if (!mounted || attempt != _generation) return;
      setState(() {
        _reply = result.content;
        _replyMeta = '200 OK · CACHE ${result.cache}';
      });
      final overview = await api.overview();
      if (mounted && attempt == _generation) {
        setState(() => _overview = overview);
      }
    } catch (e) {
      if (mounted && attempt == _generation) {
        setState(() => _error = e.toString());
      }
    } finally {
      if (mounted && attempt == _generation) setState(() => _busy = false);
    }
  }

  Widget _card(String title, List<Widget> children) => Card(
    elevation: 0,
    color: Colors.white,
    child: Padding(
      padding: const EdgeInsets.all(20),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(title, style: Theme.of(context).textTheme.titleMedium),
          const SizedBox(height: 16),
          ...children,
        ],
      ),
    ),
  );

  Widget _overviewView() {
    final data = _overview;
    if (data == null) {
      return _card('让每个请求都有迹可循', [
        const Text('网站与 App 共享网关状态、限流和请求记录。先到连接设置中配置你的实例。'),
        const SizedBox(height: 20),
        FilledButton(
          onPressed: () => setState(() => _tab = 2),
          child: const Text('连接我的网关'),
        ),
      ]);
    }
    final stats = data['stats'] as Map<String, dynamic>;
    final total = stats['requests'] as int;
    final success = total == 0
        ? '—'
        : '${((total - (stats['errors'] as int)) / total * 100).toStringAsFixed(1)}%';
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        _card('实例已连接', [
          Chip(
            avatar: const Icon(
              Icons.circle,
              size: 12,
              color: Color(0xFF087E68),
            ),
            label: Text(
              data['provider'] == 'mock'
                  ? '本地模拟模型 · 无 API 费用'
                  : '真实 OpenAI 兼容上游',
            ),
          ),
          const SizedBox(height: 8),
          Text('服务节点：${data['served_by']}'),
          Text('共享限流：${data['rate_limit_per_minute']} 次 / 分钟'),
          Text('缓存时长：${data['cache_ttl_seconds']} 秒'),
        ]),
        _card('共享运行指标', [
          Wrap(
            spacing: 28,
            runSpacing: 20,
            children: [
              _metric('累计请求', '$total'),
              _metric('成功率', success),
              _metric('平均耗时', '${stats['average_latency_ms']} ms'),
              _metric('缓存命中', '${stats['cache_hits']}'),
            ],
          ),
        ]),
        _card('最近请求', [
          const Text(
            '包含网站与 App 的请求。不记录消息正文。',
            style: TextStyle(color: Colors.blueGrey, fontSize: 12),
          ),
          const SizedBox(height: 12),
          if ((data['recent_requests'] as List).isEmpty)
            const Text('还没有请求，去试验台发送第一条消息。'),
          ...(data['recent_requests'] as List).map(
            (event) => ListTile(
              contentPadding: EdgeInsets.zero,
              leading: Icon(
                event['status'] < 400
                    ? Icons.check_circle_outline
                    : Icons.error_outline,
                color: event['status'] < 400 ? Colors.teal : Colors.red,
              ),
              title: Text(
                '${event['status']} · ${event['provider']} · ${event['cached'] ? 'HIT' : 'MISS'}',
                style: const TextStyle(fontSize: 13),
              ),
              subtitle: Text(
                '${event['id']}\n${DateTime.fromMillisecondsSinceEpoch(event['time'] * 1000).toLocal()}',
                style: const TextStyle(fontSize: 10),
              ),
              trailing: Text('${event['latency_ms']} ms'),
              isThreeLine: true,
            ),
          ),
        ]),
      ],
    );
  }

  Widget _metric(String label, String value) => SizedBox(
    width: 125,
    child: Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          label,
          style: const TextStyle(color: Colors.blueGrey, fontSize: 12),
        ),
        const SizedBox(height: 5),
        Text(
          value,
          style: const TextStyle(fontSize: 27, fontWeight: FontWeight.w600),
        ),
      ],
    ),
  );

  Widget _playgroundView() => _card('请求试验台', [
    const Text(
      'gateway-default',
      style: TextStyle(fontFamily: 'monospace', color: Colors.teal),
    ),
    const SizedBox(height: 16),
    TextField(
      controller: _prompt,
      maxLines: 5,
      maxLength: 12000,
      decoration: const InputDecoration(labelText: '消息内容'),
    ),
    const SizedBox(height: 12),
    FilledButton.icon(
      onPressed: _busy || _api == null ? null : _send,
      icon: const Icon(Icons.north_east),
      label: const Text('发送请求'),
    ),
    if (_api == null)
      const Padding(
        padding: EdgeInsets.only(top: 8),
        child: Text('请先在连接设置中连接网关。'),
      ),
    const Divider(height: 32),
    Text(_replyMeta, style: const TextStyle(color: Colors.teal, fontSize: 11)),
    const SizedBox(height: 12),
    SelectableText(_reply),
  ]);

  Widget _settingsView() => _card('连接设置', [
    const Text('管理令牌仅保留在本次运行内存中。真机请填写可达的 HTTPS 地址；localhost 指向手机自身。'),
    const SizedBox(height: 20),
    TextField(
      controller: _endpoint,
      keyboardType: TextInputType.url,
      autocorrect: false,
      decoration: const InputDecoration(
        labelText: '网关地址',
        hintText: 'https://gateway.example.com',
      ),
    ),
    const SizedBox(height: 16),
    TextField(
      controller: _token,
      obscureText: true,
      autocorrect: false,
      enableSuggestions: false,
      decoration: const InputDecoration(labelText: 'ADMIN_TOKEN'),
    ),
    const SizedBox(height: 20),
    Wrap(
      spacing: 12,
      children: [
        FilledButton(
          onPressed: _busy ? null : _connect,
          child: const Text('连接实例'),
        ),
        TextButton(
          onPressed: _busy
              ? null
              : () {
                  _generation++;
                  setState(() {
                    _api = null;
                    _overview = null;
                    _token.clear();
                    _error = null;
                    _reply = '已断开连接。';
                    _replyMeta = '';
                  });
                },
          child: const Text('断开并清除令牌'),
        ),
      ],
    ),
  ]);

  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(
      title: const Text(
        'harbor.',
        style: TextStyle(fontWeight: FontWeight.w700, letterSpacing: -1),
      ),
      actions: [
        IconButton(
          tooltip: '刷新状态',
          onPressed: _busy || _api == null ? null : _refresh,
          icon: const Icon(Icons.refresh),
        ),
      ],
    ),
    body: SafeArea(
      child: Align(
        alignment: Alignment.topCenter,
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 760),
          child: ListView(
            padding: const EdgeInsets.all(16),
            children: [
              if (_busy) const LinearProgressIndicator(),
              if (_error != null)
                Card(
                  color: Theme.of(context).colorScheme.errorContainer,
                  child: Padding(
                    padding: const EdgeInsets.all(16),
                    child: Text(_error!),
                  ),
                ),
              Padding(
                padding: const EdgeInsets.fromLTRB(4, 12, 4, 20),
                child: Text(
                  ['你的模型，你的基础设施。', '从一个请求开始。', '掌握入口，也掌握数据。'][_tab],
                  style: Theme.of(context).textTheme.headlineSmall,
                ),
              ),
              [_overviewView, _playgroundView, _settingsView][_tab](),
            ],
          ),
        ),
      ),
    ),
    bottomNavigationBar: NavigationBar(
      selectedIndex: _tab,
      onDestinationSelected: (value) => setState(() => _tab = value),
      destinations: const [
        NavigationDestination(
          icon: Icon(Icons.dashboard_outlined),
          label: '概览',
        ),
        NavigationDestination(
          icon: Icon(Icons.play_circle_outline),
          label: '试验台',
        ),
        NavigationDestination(icon: Icon(Icons.settings_outlined), label: '连接'),
      ],
    ),
  );
}
