// On-host integration test: real widgets + real networking + real mock robot.
//
// `flutter test integration_test/...` runs the app under the integration_test
// binding, which uses real async (not the fake-async zone `testWidgets` uses),
// so the production RobotApiService's http.Client can open real sockets to the
// loopback mock robot. This closes the UI-state gap that a plain widget test
// cannot: entering the address and pressing Ping must drive the real client
// through a real HTTP round-trip and visibly flip the badge to "Connected".

import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:integration_test/integration_test.dart';
import 'package:provider/provider.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:amr_controller/providers/robot_provider.dart';
import 'package:amr_controller/screens/connection_screen.dart';
import 'package:amr_controller/services/robot_api_service.dart';

import 'package:amr_controller/testing/mock_robot.dart';

void main() {
  IntegrationTestWidgetsFlutterBinding.ensureInitialized();

  testWidgets('enter address -> ping -> badge becomes Connected (real HTTP)',
      (WidgetTester tester) async {
    SharedPreferences.setMockInitialValues({});

    // The integration binding does not install the hermetic HttpOverrides, but
    // be explicit so any future binding change cannot silently turn this into a
    // "400-forever" test.
    final prev = HttpOverrides.current;
    HttpOverrides.global = null;
    addTearDown(() => HttpOverrides.global = prev);

    final robot = await MockRobot.start();
    addTearDown(robot.stop);

    final provider = RobotProvider(api: RobotApiService());
    addTearDown(provider.dispose);

    await tester.pumpWidget(
      ChangeNotifierProvider<RobotProvider>.value(
        value: provider,
        child: const MaterialApp(home: ConnectionScreen()),
      ),
    );

    expect(find.text('Disconnected'), findsOneWidget);

    await tester.enterText(find.byType(TextField), 'localhost:${robot.port}');
    await tester.pump();

    await tester.tap(find.widgetWithText(FilledButton, 'Ping / check connection'));

    // Real async: the ping (health + applications/state + telemetry) needs real
    // time. Wait for the provider to flip, not a fixed sleep.
    final deadline = DateTime.now().add(const Duration(seconds: 5));
    while (DateTime.now().isBefore(deadline) && !provider.isConnected) {
      await tester.pump(const Duration(milliseconds: 50));
    }

    expect(provider.isConnected, isTrue,
        reason: 'provider never connected; requests=${robot.requests}');
    expect(find.text('Connected'), findsOneWidget);
    expect(find.text('Disconnected'), findsNothing);
  });
}