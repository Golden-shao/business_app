import 'dart:convert';

import 'package:business_app/gateway_api.dart';
import 'package:business_app/main.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

Map<String, dynamic> overview([int total = 7]) => {
  'provider': 'mock',
  'served_by': 'pod-test',
  'rate_limit_per_minute': 30,
  'cache_ttl_seconds': 60,
  'stats': {
    'requests': total,
    'errors': 0,
    'cache_hits': 2,
    'average_latency_ms': 4,
  },
  'recent_requests': [],
};
http.Response overviewResponse([int total = 7]) => http.Response(
  jsonEncode(overview(total)),
  200,
  headers: {'content-type': 'application/json'},
);

Future<void> connect(
  WidgetTester tester,
  http.Client client, {
  DateTime Function()? now,
}) async {
  tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.resumed);
  await tester.pumpWidget(HarborApp(client: client, now: now));
  await tester.tap(find.text('连接我的网关'));
  await tester.pumpAndSettle();
  await tester.enterText(find.byType(TextField).at(1), 'admin-test-token-1234');
  await tester.ensureVisible(find.text('连接实例'));
  await tester.tap(find.text('连接实例'));
  await tester.pumpAndSettle();
}

void main() {
  testWidgets(
    'a failed status refresh preserves a successful completion without resending',
    (tester) async {
      var reads = 0;
      var sends = 0;
      final client = MockClient((request) async {
        if (request.method == 'POST') {
          sends++;
          return http.Response(
            jsonEncode({
              'choices': [
                {
                  'message': {'content': '已完成的模型回复'},
                },
              ],
            }),
            200,
            headers: {
              'content-type': 'application/json; charset=utf-8',
              'x-cache': 'MISS',
              'x-request-id': 'completed-request',
            },
          );
        }
        return ++reads == 1
            ? overviewResponse()
            : http.Response('unavailable', 503);
      });
      await connect(tester, client);
      await tester.tap(find.text('试验台'));
      await tester.pumpAndSettle();
      await tester.ensureVisible(find.text('发送请求'));
      await tester.tap(find.text('发送请求'));
      await tester.pumpAndSettle();
      expect(sends, 1);
      await tester.drag(find.byType(ListView), const Offset(0, -450));
      await tester.pumpAndSettle();
      expect(
        find.byWidgetPredicate(
          (widget) => widget is SelectableText && widget.data == '已完成的模型回复',
        ),
        findsOneWidget,
      );
      expect(find.text('200 OK · CACHE MISS'), findsOneWidget);
      await tester.drag(find.byType(ListView), const Offset(0, 800));
      await tester.pumpAndSettle();
      expect(find.textContaining('当前为上次数据'), findsOneWidget);
      await tester.pump(const Duration(seconds: 6));
      await tester.pump();
      expect(sends, 1);
      await tester.pumpWidget(const SizedBox());
    },
  );

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

  for (final status in [401, 429, 503]) {
    test('HTTP $status stays actionable when a proxy returns HTML', () async {
      final api = GatewayApi(
        'http://localhost:8000',
        'a' * 20,
        MockClient(
          (_) async => http.Response(
            '<html>proxy error</html>',
            status,
            headers: {'retry-after': '2', 'x-request-id': 'request-test'},
          ),
        ),
      );
      await expectLater(
        api.send('hello'),
        throwsA(
          isA<GatewayException>()
              .having((e) => e.statusCode, 'status', status)
              .having((e) => e.requestId, 'request id', 'request-test')
              .having(
                (e) => e.retryAfter,
                'retry seconds',
                status == 429 ? 2 : 0,
              ),
        ),
      );
    });
  }

  test('non-JSON success is explained without a parsing stack trace', () async {
    final api = GatewayApi(
      'http://localhost:8000',
      'a' * 20,
      MockClient((_) async => http.Response('<html>wrong server</html>', 200)),
    );
    await expectLater(
      api.overview(),
      throwsA(
        isA<GatewayException>().having(
          (e) => e.message,
          'message',
          contains('JSON'),
        ),
      ),
    );
  });

  testWidgets('connects with credentials and renders shared metrics', (
    tester,
  ) async {
    final client = MockClient((request) async {
      expect(request.url.path, '/api/overview');
      expect(request.headers['Authorization'], 'Bearer admin-test-token-1234');
      expect(request.headers['X-Harbor-Client'], 'flutter');
      return overviewResponse();
    });
    await connect(tester, client);
    expect(find.text('实例已连接'), findsOneWidget);
    expect(find.text('7'), findsOneWidget);
    expect(find.text('服务节点：pod-test'), findsOneWidget);
    await tester.pumpWidget(const SizedBox());
  });

  testWidgets(
    'syncs automatically, pauses in background and stops after disconnect',
    (tester) async {
      var reads = 0;
      final client = MockClient((_) async => overviewResponse(6 + ++reads));
      await connect(tester, client);
      expect(reads, 1);
      await tester.pump(const Duration(seconds: 5));
      await tester.pump();
      expect(reads, 2);
      expect(find.text('8'), findsOneWidget);
      tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.paused);
      await tester.pump(const Duration(seconds: 10));
      expect(reads, 2);
      tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.resumed);
      await tester.pumpAndSettle();
      expect(reads, 3);
      await tester.tap(find.text('连接'));
      await tester.pumpAndSettle();
      await tester.ensureVisible(find.text('断开并清除令牌'));
      await tester.tap(find.text('断开并清除令牌'));
      await tester.pumpAndSettle();
      final before = reads;
      await tester.pump(const Duration(seconds: 10));
      expect(reads, before);
      expect(
        tester.widget<TextField>(find.byType(TextField).at(1)).controller!.text,
        isEmpty,
      );
      await tester.pumpWidget(const SizedBox());
    },
  );

  testWidgets('rate limit disables sending until deadline without resending', (
    tester,
  ) async {
    var now = DateTime(2026, 10, 25);
    var sends = 0;
    final client = MockClient((request) async {
      if (request.method == 'POST') {
        sends++;
        return http.Response(
          'proxy rate limit',
          429,
          headers: {'retry-after': '2', 'x-request-id': 'limited-request'},
        );
      }
      return overviewResponse();
    });
    await connect(tester, client, now: () => now);
    await tester.tap(find.text('试验台'));
    await tester.pumpAndSettle();
    await tester.ensureVisible(find.text('发送请求'));
    await tester.tap(find.text('发送请求'));
    await tester.pumpAndSettle();
    expect(sends, 1);
    expect(find.text('2 秒后可重试'), findsOneWidget);
    expect(
      tester
          .widget<FilledButton>(find.widgetWithText(FilledButton, '2 秒后可重试'))
          .onPressed,
      isNull,
    );
    now = now.add(const Duration(seconds: 3));
    await tester.pump(const Duration(seconds: 3));
    expect(find.text('发送请求'), findsOneWidget);
    expect(sends, 1);
    await tester.pumpWidget(const SizedBox());
  });
}
