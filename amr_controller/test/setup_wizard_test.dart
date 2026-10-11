// Tests for the first-run setup wizard and its provider logic.
//
// These cover the three things the wizard exists to do:
//   1. probe each endpoint *individually* (not all-or-nothing),
//   2. surface a fatal precondition before the operator can drive,
//   3. show live sensor readings — honouring the backend's "-1 = clear" rule.

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:provider/provider.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:amr_controller/features/setup/setup_wizard.dart';
import 'package:amr_controller/main.dart';
import 'package:amr_controller/models/app_state.dart';
import 'package:amr_controller/providers/robot_provider.dart';
import 'package:amr_controller/services/robot_api_service.dart';
import 'package:amr_controller/theme/theme.dart';

/// A robot API double: every endpoint succeeds unless named in [failPaths].
class _FakeApi extends RobotApiService {
  _FakeApi({this.failPaths = const <String>{}});

  final Set<String> failPaths;

  static const _healthyTelemetry = <String, dynamic>{
    'system': {'connected': true, 'mode': 'MANUAL'},
    'battery': {'percentage': 90.0},
    'sensors': {'front_cm': 42, 'left_cm': -1, 'right_cm': 55, 'rear_cm': 120},
  };

  @override
  Future<Map<String, dynamic>> getJson(String origin, String path) async {
    if (failPaths.contains(path)) {
      throw RobotApiException('HTTP 500 from $path', statusCode: 500);
    }
    return <String, dynamic>{};
  }

  @override
  Future<Map<String, dynamic>> fetchHealth(String origin) async =>
      <String, dynamic>{'status': 'OK'};

  @override
  Future<Map<String, dynamic>> fetchTelemetry(String origin) async =>
      _healthyTelemetry;

  @override
  Future<Map<String, dynamic>> fetchApplications(String origin) async =>
      <String, dynamic>{};

  @override
  Future<Map<String, dynamic>> fetchMap(String origin) async =>
      <String, dynamic>{};

  @override
  Future<Map<String, dynamic>> fetchCameraStatus(String origin) async =>
      <String, dynamic>{'status': 'AVAILABLE', 'has_frame': true};

  @override
  Future<Map<String, dynamic>> fetchConnectivity(String origin) async =>
      <String, dynamic>{};

  @override
  Future<Map<String, dynamic>> fetchHeatmap(String origin) async =>
      <String, dynamic>{};
}

Widget _host(Widget child, RobotProvider p) =>
    ChangeNotifierProvider<RobotProvider>.value(
      value: p,
      child: MaterialApp(theme: buildAppTheme(), home: child),
    );

void main() {
  setUp(() => SharedPreferences.setMockInitialValues(<String, Object>{}));

  group('diagnostics', () {
    test('probes every endpoint individually and all pass when reachable',
        () async {
      final p = RobotProvider(api: _FakeApi());
      addTearDown(p.dispose);
      await p.loadSavedConnection();

      await p.runDiagnostics();

      expect(p.diagnostics, isNotEmpty);
      expect(p.diagnostics.every((c) => c.ok), isTrue,
          reason: 'every endpoint should report OK against a healthy robot');
      expect(p.coreEndpointsOk, isTrue);
      expect(p.connection, RobotConnectionState.connected);
    });

    test('a failing REQUIRED endpoint is reported, not swallowed', () async {
      final p = RobotProvider(api: _FakeApi(failPaths: {'/health'}));
      addTearDown(p.dispose);
      await p.loadSavedConnection();

      await p.runDiagnostics();

      final health = p.diagnostics.firstWhere((c) => c.path == '/health');
      expect(health.ok, isFalse);
      expect(health.required, isTrue);
      expect(health.fix, isNotNull, reason: 'a failure must come with a fix');
      expect(p.coreEndpointsOk, isFalse);
    });

    test('a failing OPTIONAL endpoint does not make the robot unusable',
        () async {
      final p = RobotProvider(api: _FakeApi(failPaths: {'/camera/status'}));
      addTearDown(p.dispose);
      await p.loadSavedConnection();

      await p.runDiagnostics();

      final cam = p.diagnostics.firstWhere((c) => c.path == '/camera/status');
      expect(cam.ok, isFalse);
      expect(cam.required, isFalse);
      expect(p.coreEndpointsOk, isTrue,
          reason: 'a missing camera must not block setup');
    });
  });

  group('preflight', () {
    test('is fatal when the robot is unreachable', () {
      final p = RobotProvider(api: _FakeApi());
      addTearDown(p.dispose);

      final items = p.preflight();

      expect(items.single.severity, PreflightSeverity.fatal);
      expect(items.single.title, 'NO ROBOT CONNECTION');
      expect(items.single.fix, isNotNull);
    });

    test('is fatal for E-STOP and a close obstacle', () {
      final p = RobotProvider(api: _FakeApi());
      addTearDown(p.dispose);
      p.connection = RobotConnectionState.connected;
      p.telemetry = const TelemetryState(
        connected: true,
        mode: 'MANUAL',
        emergencyStop: true,
        frontCm: 12,
      );

      final titles = p.preflight().map((i) => i.title).toList();

      expect(titles, contains('E-STOP ACTIVE'));
      expect(titles, contains('OBSTACLE TOO CLOSE'));
      expect(p.fatalPreflight(), isNotEmpty);
    });

    test('passes cleanly when connected and healthy', () {
      final p = RobotProvider(api: _FakeApi());
      addTearDown(p.dispose);
      p.connection = RobotConnectionState.connected;
      p.telemetry = const TelemetryState(
        connected: true,
        mode: 'MANUAL',
        batteryPercentage: 90,
        frontCm: 200,
      );

      final items = p.preflight();

      expect(items.single.severity, PreflightSeverity.info);
      expect(p.fatalPreflight(), isEmpty);
    });

    test('warns (not fatal) in simulation mode', () {
      final p = RobotProvider(api: _FakeApi());
      addTearDown(p.dispose);
      p.simulation = true;

      final items = p.preflight();

      expect(items.single.severity, PreflightSeverity.warning);
      expect(items.single.title, 'SIMULATION MODE');
    });
  });

  group('root gate', () {
    testWidgets('first run opens the setup wizard', (tester) async {
      final p = RobotProvider(api: _FakeApi());
      await p.loadSavedConnection();

      await tester.pumpWidget(AmrControllerApp(provider: p));
      await tester.pump();

      expect(find.byType(SetupWizard), findsOneWidget);
      expect(find.text('Welcome to the AMR Controller'), findsOneWidget);
    });

    testWidgets('after setup the console shell is shown', (tester) async {
      SharedPreferences.setMockInitialValues(
          <String, Object>{'amr.setup_complete': true});
      final p = RobotProvider(api: _FakeApi());
      await p.loadSavedConnection();

      await tester.pumpWidget(AmrControllerApp(provider: p));
      await tester.pump();

      expect(find.byType(SetupWizard), findsNothing);
      expect(find.text('Dashboard'), findsWidgets);
      expect(find.text('Teleop'), findsWidgets);
    });
  });

  group('wizard flow', () {
    testWidgets('guidance -> connect test -> checks -> live sensor readings',
        (tester) async {
      final p = RobotProvider(api: _FakeApi());
      await p.loadSavedConnection();
      await tester.pumpWidget(_host(const SetupWizard(), p));

      // Step 0: guidance is shown.
      expect(find.text('Welcome to the AMR Controller'), findsOneWidget);
      expect(find.text('On the robot (Raspberry Pi)'), findsOneWidget);

      // Step 1: run the connection test.
      await tester.tap(find.text('Next'));
      await tester.pumpAndSettle();
      expect(find.text('Connect to the robot'), findsOneWidget);

      await tester.tap(find.text('Run connection test'));
      await tester.pumpAndSettle();
      expect(find.text('Robot liveness'), findsOneWidget);
      expect(find.text('OK'), findsWidgets);

      // Step 2: preflight passes and the sensors read out.
      await tester.tap(find.text('Next'));
      await tester.pumpAndSettle();
      expect(find.text('ALL CHECKS PASSED'), findsOneWidget);
      expect(find.text('42 cm'), findsOneWidget, reason: 'front sensor');
      expect(find.text('clear'), findsOneWidget,
          reason: '-1 means no echo (clear), never 0 cm');
      expect(find.text('90'), findsWidgets, reason: 'battery %');

      // Step 3: ready.
      await tester.tap(find.text('Next'));
      await tester.pumpAndSettle();
      expect(find.text('Setup complete'), findsOneWidget);

      // The successful connect started the 1.5 s poll timer. Unmount the tree and
      // dispose the provider so the framework sees no pending timer.
      await tester.pumpWidget(const SizedBox.shrink());
      p.dispose();
    });
  });
}
