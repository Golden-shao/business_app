import 'dart:async';
import 'dart:convert';

import 'package:http/http.dart' as http;

class GatewayException implements Exception {
  const GatewayException(this.message);
  final String message;
  @override
  String toString() => message;
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

  Future<http.Response> _request(
    String path, [
    Map<String, dynamic>? body,
  ]) async {
    try {
      final headers = {
        'Authorization': 'Bearer $token',
        'Content-Type': 'application/json',
      };
      final uri = base.resolve(path);
      final response =
          await (body == null
                  ? client.get(uri, headers: headers)
                  : client.post(uri, headers: headers, body: jsonEncode(body)))
              .timeout(const Duration(seconds: 35));
      if (response.statusCode >= 400) {
        final data =
            jsonDecode(utf8.decode(response.bodyBytes)) as Map<String, dynamic>;
        final detail = data['detail'] is String ? data['detail'] : '请求参数不正确';
        throw GatewayException('${response.statusCode} · $detail');
      }
      return response;
    } on TimeoutException {
      throw const GatewayException('连接超时，请检查地址或稍后重试。');
    } on http.ClientException {
      throw const GatewayException('无法连接网关，请检查网络、地址和服务状态。');
    } on FormatException {
      throw const GatewayException('网关返回了无法识别的数据，请检查服务地址。');
    }
  }

  Future<Map<String, dynamic>> overview() async {
    final response = await _request('/api/overview');
    return jsonDecode(utf8.decode(response.bodyBytes)) as Map<String, dynamic>;
  }

  Future<({String content, String cache})> send(String message) async {
    final response = await _request('/api/playground', {
      'model': 'gateway-default',
      'messages': [
        {'role': 'user', 'content': message},
      ],
    });
    final data =
        jsonDecode(utf8.decode(response.bodyBytes)) as Map<String, dynamic>;
    return (
      content: data['choices'][0]['message']['content'] as String,
      cache: response.headers['x-cache'] ?? 'MISS',
    );
  }
}
