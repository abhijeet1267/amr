// Android runtime integration test.
//
// Runs the REAL app shell (RootShell) — not a single screen — under the
// integration_test binding on a real Android device/emulator, with the real
// RobotApiService/RobotProvider opening real sockets to MockRobot on loopback.
// This is the same "real client → real HTTP → mock robot → real state → real
// UI" chain as connection_test.dart, but driven through the production entry
// point, which is exactly what a user launches.
//
// Instrumented against the same mock robot everywhere, so the assertions are
// deterministic and device-independent (no physical robot assumed).

import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:integration_test/integration_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:amr_controller/main.dart';
import 'package:amr_controller/providers/robot_provider.dart';
import 'package:amr_controller/services/robot_api_service.dart';
import 'package:amr_controller/testing/mock_robot.dart';

void main() {
  IntegrationTestWidgetsFlutterBinding.ensureInitialized();

  testWidgets('full app shell connects and drives the mock robot on-device',
      (WidgetTester tester) async {
    SharedPreferences.setMockInitialValues({});

    final prev = HttpOverrides.current;
    HttpOverrides.global = null;
    addTearDown(() => HttpOverrides.global = prev);

    final robot = await MockRobot.start();
    addTearDown(robot.stop);

    final provider = RobotProvider(api: RobotApiService());
    // The app's ChangeNotifierProvider now owns and disposes this provider when
    // the tree is torn down, so do NOT also dispose it here (double-dispose
    // trips ChangeNotifier's assertion).

    // The production root shell, with the mock-robot-wired provider injected via
    // the app's DI seam (same channel the production api is injected through).
    await tester.pumpWidget(AmrControllerApp(provider: provider));
    await tester.pump();

    // The shell's three nav destinations render.
    expect(find.text('Applications'), findsWidgets);
    expect(find.text('Teleop'), findsWidgets);

    // Navigate to Connection.
    await tester.tap(find.widgetWithText(NavigationDestination, 'Connection'));
    await tester.pump(const Duration(milliseconds: 300));

    // Enter the mock robot address and ping.
    await tester.enterText(find.byType(TextField), '127.0.0.1:${robot.port}');
    await tester.pump();
    await tester.tap(find.widgetWithText(FilledButton, 'Ping / check connection'));

    final deadline = DateTime.now().add(const Duration(seconds: 8));
    while (DateTime.now().isBefore(deadline) && !provider.isConnected) {
      await tester.pump(const Duration(milliseconds: 60));
    }

    expect(provider.isConnected, isTrue,
        reason: 'app never connected; requests=${robot.requests}');
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 50));
    expect(find.text('Connected'), findsWidgets);

    // Navigate to Teleop and drive the robot through the real command path.
    await tester.tap(find.widgetWithText(NavigationDestination, 'Teleop'));
    await tester.pump(const Duration(milliseconds: 300));

    // Every real command is mediated by RobotProvider.command() below; the UI
    // joystick maps to the same verbs but is pointer-driven, so we drive the
    // provider directly here — the transport under test is unchanged.

    // Robot boots IDLE: motion rejected until MANUAL.
    final rejected = await provider.command('forward', speed: 50);
    expect(rejected, isFalse);

    expect(await provider.command('mode', mode: 'manual'), isTrue);
    expect(robot.mode, 'MANUAL');

    expect(await provider.command('forward', speed: 50), isTrue);
    expect(await provider.command('stop'), isTrue);

    // E-STOP -> SAFETY_STOP -> motion vetoed, stop still allowed.
    expect(await provider.command('estop'), isTrue);
    expect(robot.mode, 'SAFETY_STOP');

    final blocked = await provider.command('forward', speed: 50);
    expect(blocked, isFalse);
    expect(provider.lastCommandError, contains('motion not allowed'));
    expect(await provider.command('stop'), isTrue);

    // The telemetry the app parsed is the mock robot's deterministic values.
    expect(provider.telemetry, isNotNull);
    expect(provider.telemetry!.batteryPercentage, robot.batteryPercentage);
  });
}