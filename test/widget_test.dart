import 'dart:convert';

import 'package:business_app/gateway_api.dart';
import 'package:business_app/main.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

void main() {
  test('remote credentials require HTTPS', () {
    expect(
      () => GatewayApi(
        'http://example.com',
        'a' * 20,
        MockClient((_) async => http.Response('', 200)),
      ),
      throwsA(isA<GatewayException>()),
    );
  });
  testWidgets('connects with credentials and renders shared metrics', (
    tester,
  ) async {
    final client = MockClient((request) async {
      expect(request.url.path, '/api/overview');
      expect(request.headers['Authorization'], 'Bearer admin-test-token-1234');
      return http.Response(
        jsonEncode({
          'provider': 'mock',
          'served_by': 'pod-test',
          'rate_limit_per_minute': 30,
          'cache_ttl_seconds': 60,
          'stats': {
            'requests': 7,
            'errors': 0,
            'cache_hits': 2,
            'average_latency_ms': 4,
          },
          'recent_requests': [],
        }),
        200,
        headers: {'content-type': 'application/json'},
      );
    });
    await tester.pumpWidget(HarborApp(client: client));
    await tester.tap(find.text('连接我的网关'));
    await tester.pumpAndSettle();
    await tester.enterText(
      find.byType(TextField).at(1),
      'admin-test-token-1234',
    );
    await tester.ensureVisible(find.text('连接实例'));
    await tester.tap(find.text('连接实例'));
    await tester.pumpAndSettle();
    expect(find.text('实例已连接'), findsOneWidget);
    expect(find.text('7'), findsOneWidget);
    expect(find.text('服务节点：pod-test'), findsOneWidget);
  });
}
