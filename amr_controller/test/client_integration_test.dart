// End-to-end client integration: the *real* production networking code
// (RobotApiService + RobotProvider) driven against MockRobot, a faithful
// in-process re-creation of the robot's HTTP contract.
//
// The chain under test is exactly the production path:
//
//   RobotProvider.command() / .ping()
//     -> RobotApiService.sendCommand() / fetchHealth() / fetchTelemetry()
//       -> http.Client()  (real IO)
//         -> MockRobot HttpServer (loopback)
//           -> response bytes
//             -> RobotApiService JSON parse / status check
//               -> RobotProvider state mutation (connection / telemetry /
//                  lastCommandError)
//
// No network stack is mocked at the dart:io layer: these tests open real
// sockets. Only the *peer* (the robot) is a test double, which is the point.

import 'package:flutter_test/flutter_test.dart';

import 'package:amr_controller/providers/robot_provider.dart';
import 'package:amr_controller/services/robot_api_service.dart';

import 'package:amr_controller/testing/mock_robot.dart';

void main() {
  late MockRobot robot;
  late RobotProvider provider;

  setUp(() async {
    robot = await MockRobot.start();
    // Real production client against the mock robot's loopback origin.
    provider = RobotProvider(api: RobotApiService());
    provider.host = '127.0.0.1:${robot.port}';
  });

  tearDown(() async {
    provider.dispose();
    // Let the poll timer (if any) unwind before closing the server.
    await Future<void>.delayed(const Duration(milliseconds: 50));
    await robot.stop();
  });

  group('connection', () {
    test('disconnected -> ping -> connected, against a real HTTP round trip',
        () async {
      expect(provider.connection, RobotConnectionState.disconnected);
      expect(provider.isConnected, isFalse);

      final ok = await provider.ping();

      expect(ok, isTrue);
      expect(provider.connection, RobotConnectionState.connected);
      expect(provider.isConnected, isTrue);
      expect(provider.connectionDetail, contains('OK'));

      // ping seeds the registry + telemetry in the same request burst.
      expect(provider.registry, isNotNull);
      expect(provider.registry!.applications, hasLength(2));
      expect(provider.telemetry, isNotNull);
      // The client actually issued GET /health, /applications/state, /telemetry.
      final paths = robot.requests.map((r) => r.path).toSet();
      expect(paths, containsAll(['/health', '/applications/state', '/telemetry']));
    });

    test('ping against an unreachable host goes to error, not connected',
        () async {
      provider.host = '127.0.0.1:1'; // nothing listens here
      final ok = await provider.ping();
      expect(ok, isFalse);
      expect(provider.connection, RobotConnectionState.error);
      expect(provider.isConnected, isFalse);
      expect(provider.connectionDetail, isNotEmpty);
    });
  });

  group('motion', () {
    test('connect, MANUAL, forward, stop — the mock robot saw exact requests',
        () async {
      await provider.ping();

      // Robot boots IDLE: motion must be rejected before MANUAL.
      final rejected = await provider.command('forward', speed: 100);
      expect(rejected, isFalse);
      expect(provider.lastCommandError, contains('mode'));

      // Switch to MANUAL.
      final modeOk = await provider.command('mode', mode: 'manual');
      expect(modeOk, isTrue);
      expect(robot.mode, 'MANUAL');

      // Real motion commands reach the robot and it records them.
      final fwd = await provider.command('forward', speed: 100);
      expect(fwd, isTrue);
      final stp = await provider.command('stop');
      expect(stp, isTrue);

      final cmds = robot.commands;
      expect(cmds.map((c) => c['cmd']).toList(),
          ['forward', 'mode', 'forward', 'stop']);
      expect(cmds[2]['speed'], 100);
      expect(robot.requests.any((r) => r.method == 'POST' && r.path == '/command'),
          isTrue);
    });
  });

  group('invalid command', () {
    test('out-of-range speed surfaces the HTTP 400 refusal', () async {
      await provider.ping();
      await provider.command('mode', mode: 'manual');

      final ok = await provider.command('forward', speed: 99999);
      expect(ok, isFalse);
      expect(provider.lastCommandOk, isFalse);
      expect(provider.lastCommandError, contains('speed'));
    });
  });

  group('E-STOP safety', () {
    test('estop -> SAFETY_STOP -> forward rejected, but stop stays allowed',
        () async {
      await provider.ping();
      await provider.command('mode', mode: 'manual');
      expect(robot.mode, 'MANUAL');

      final estop = await provider.command('estop');
      expect(estop, isTrue);
      expect(robot.mode, 'SAFETY_STOP');

      // Motion is vetoed while stopped.
      final fwd = await provider.command('forward', speed: 100);
      expect(fwd, isFalse);
      expect(provider.lastCommandError, contains('motion not allowed'));

      // stop() is a distinct, non-motion verb and remains accepted.
      final stp = await provider.command('stop');
      expect(stp, isTrue);
    });
  });

  group('telemetry', () {
    test('deterministic telemetry is parsed into the app model', () async {
      await provider.ping();

      final t = provider.telemetry!;
      expect(t.batteryPercentage, robot.batteryPercentage);
      expect(t.batteryVoltage, robot.batteryVoltage);
      expect(t.frontCm, robot.frontCm);
      expect(t.speedMps, robot.speedMps);
      expect(t.connected, isTrue);
      expect(t.mode, isNotNull);
      expect(t.simulated, isTrue);
    });
  });
}