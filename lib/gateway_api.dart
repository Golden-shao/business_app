import 'dart:async';
import 'dart:convert';

import 'package:http/http.dart' as http;

class GatewayException implements Exception {
  const GatewayException(
    this.message, {
    this.statusCode,
    this.retryAfter = 0,
    this.requestId,
  });
  final String message;
  final int? statusCode;
  final int retryAfter;
  final String? requestId;
  @override
  String toString() =>
      requestId == null ? message : '$message\n请求 ID：$requestId';
}

class GatewayApi {
  GatewayApi(String baseUrl, this.token, this.client)
    : base = Uri.parse(baseUrl) {
    if (!base.hasAuthority ||
        !['http', 'https'].contains(base.scheme) ||
        base.userInfo.isNotEmpty ||
        base.hasQuery ||
        base.hasFragment ||
        (base.path.isNotEmpty && base.path != '/')) {
      throw const GatewayException('请填写不含路径、凭证或参数的 HTTP(S) 网关地址。');
    }
    if (base.scheme == 'http' &&
        !['localhost', '127.0.0.1', '::1'].contains(base.host)) {
      throw const GatewayException('远程网关请使用 HTTPS，以保护管理令牌。');
    }
    if (token.length < 16) throw const GatewayException('管理令牌至少需要 16 个字符。');
  }
  final Uri base;
  final String token;
  final http.Client client;

  static String _failureMessage(int status) => switch (status) {
    401 => '管理令牌无效或已失效，请使用 ADMIN_TOKEN 重新连接。GATEWAY_TOKEN 不能用于管理。',
    413 => '消息过长，请缩短内容后重试。',
    422 => '请求内容不符合要求，请检查消息是否为空或过长。',
    429 => '已达到共享调用限额，倒计时结束后可手动重试。消息不会自动重发。',
    502 => '模型上游暂时不可用，请检查服务端的上游配置，稍后再试。',
    503 => '网关暂未就绪，请检查后端和 Redis，恢复后会继续同步。',
    _ => '服务返回 $status，请稍后重试或检查网关日志。',
  };

  Future<http.Response> _request(
    String path, [
    Map<String, dynamic>? body,
  ]) async {
    try {
      final headers = {
        'Authorization': 'Bearer $token',
        'Content-Type': 'application/json',
        'X-Harbor-Client': 'flutter',
      };
      final uri = base.resolve(path);
      final response =
          await (body == null
                  ? client.get(uri, headers: headers)
                  : client.post(uri, headers: headers, body: jsonEncode(body)))
              .timeout(const Duration(seconds: 35));
      if (response.statusCode >= 400) {
        throw GatewayException(
          _failureMessage(response.statusCode),
          statusCode: response.statusCode,
          retryAfter: response.statusCode == 429
              ? (int.tryParse(response.headers['retry-after'] ?? '') ?? 60)
                    .clamp(1, 3600)
              : 0,
          requestId: response.headers['x-request-id'],
        );
      }
      return response;
    } on TimeoutException {
      throw const GatewayException('连接超时，请检查地址和网络，稍后重试。');
    } on http.ClientException {
      throw const GatewayException('无法连接网关，请检查网络、地址和后端进程。');
    }
  }

  Map<String, dynamic> _decode(http.Response response) {
    try {
      final data = jsonDecode(utf8.decode(response.bodyBytes));
      if (data is! Map<String, dynamic>) throw const FormatException();
      return data;
    } on FormatException {
      throw const GatewayException('服务未返回有效的 JSON 数据，请确认连接的是 Harbor 网关。');
    }
  }

  Future<Map<String, dynamic>> overview() async {
    final data = _decode(await _request('/api/overview'));
    if (data['stats'] is! Map || data['recent_requests'] is! List) {
      throw const GatewayException('实例返回的数据不完整，请确认 Harbor 服务版本。');
    }
    return data;
  }

  Future<({String content, String cache, String? requestId})> send(
    String message,
  ) async {
    final response = await _request('/api/playground', {
      'model': 'gateway-default',
      'messages': [
        {'role': 'user', 'content': message},
      ],
    });
    final data = _decode(response);
    final choices = data['choices'];
    if (choices is! List ||
        choices.isEmpty ||
        choices.first is! Map ||
        choices.first['message'] is! Map ||
        choices.first['message']['content'] is! String) {
      throw const GatewayException('模型回复格式不正确，请检查网关和上游配置。');
    }
    return (
      content: choices.first['message']['content'] as String,
      cache: response.headers['x-cache'] ?? 'MISS',
      requestId: response.headers['x-request-id'] ?? data['id'] as String?,
    );
  }
}
