// A deterministic, in-process stand-in for the robot's stdlib HTTP server.
//
// This is the TEST DOUBLE for the robot — not a copy of the client. It
// re-implements the exact HTTP contract of raspberry_pi/amr/web/server.py that
// this project's live contract checks already verified: the same endpoints,
// status codes, and command state machine (IDLE → MANUAL → motion; E-STOP →
// SAFETY_STOP; invalid speed → 400; motion gated by mode). Because it is a
// plain dart:io HttpServer on loopback, the *real* RobotApiService /
// RobotProvider / ConnectionScreen — the production networking code — can be
// exercised against it end-to-end with no external process and no flaky port
// setup.
//
// It records every request (method, path, body) so a test can assert that the
// client actually emitted the expected command byte-for-byte.

import 'dart:convert';
import 'dart:io';

class RecordedRequest {
  RecordedRequest(this.method, this.path, this.body);

  final String method;
  final String path;
  final String body;

  Map<String, dynamic>? get jsonBody {
    if (body.isEmpty) return null;
    try {
      final v = jsonDecode(body);
      return v is Map<String, dynamic> ? v : null;
    } catch (_) {
      return null;
    }
  }

  @override
  String toString() => '$method $path $body';
}

class MockRobot {
  MockRobot._(this._server, this.port);

  final HttpServer _server;
  final int port;

  /// The robot's logical mode, mirroring `RobotMode` (IDLE → MANUAL/AUTONOMOUS
  /// → SAFETY_STOP/ERROR). Starts IDLE exactly like the real firmware.
  String mode = 'IDLE';

  final List<RecordedRequest> requests = [];

  static const int maxSpeed = 255;

  // Motion verb → default speed, mirroring server.py's `_MOTION`.
  static const Map<String, int> _motionDefaults = {
    'forward': 100,
    'backward': 100,
    'rotate_left': 100,
    'rotate_right': 100,
    'turn_left': 80,
    'turn_right': 80,
  };

  /// Deterministic telemetry this robot reports.
  final double batteryPercentage = 87.5;
  final double batteryVoltage = 12.2;
  final int frontCm = 42;
  final int leftCm = 40;
  final int rightCm = 41;
  final int rearCm = 43;
  final double speedMps = 0.5;

  static Future<MockRobot> start() async {
    final server = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
    final robot = MockRobot._(server, server.port);
    server.listen(robot._handle);
    return robot;
  }

  Future<void> stop() async {
    await _server.close(force: true);
  }

  /// Every `/command` body received, in order.
  List<Map<String, dynamic>> get commands => requests
      .where((r) => r.path == '/command')
      .map((r) => r.jsonBody)
      .whereType<Map<String, dynamic>>()
      .toList();

  Future<void> _handle(HttpRequest req) async {
    final path = req.uri.path;
    final method = req.method;

    var body = '';
    if (method == 'POST') {
      body = await utf8.decoder.bind(req).join();
    }
    requests.add(RecordedRequest(method, path, body));

    int status;
    Map<String, dynamic> payload;
    if (method == 'POST' && path == '/command') {
      (status, payload) = _dispatch(jsonDecode(body) as Map<String, dynamic>);
    } else if (method == 'GET') {
      (status, payload) = _get(path);
    } else {
      (status, payload) = (404, {'error': 'not found'});
    }

    final bytes = utf8.encode(jsonEncode(payload));
    req.response
      ..statusCode = status
      ..headers.contentType = ContentType.json
      ..headers.set('Content-Length', bytes.length.toString())
      ..add(bytes);
    await req.response.close();
  }

  (int, Map<String, dynamic>) _dispatch(Map<String, dynamic> cmd) {
    final name = (cmd['cmd'] ?? '').toString().toLowerCase();

    switch (name) {
      case 'estop':
        mode = 'SAFETY_STOP';
        return (200, {'ok': true, 'mode': mode});

      case 'stop':
        return (200, {'ok': true});

      case 'mode':
        return _requestMode((cmd['mode'] ?? '').toString().toUpperCase());

      case 'forward':
      case 'backward':
      case 'rotate_left':
      case 'rotate_right':
      case 'turn_left':
      case 'turn_right':
        return _motion(name, cmd);

      default:
        return (400, {'ok': false, 'error': 'unknown command: $name'});
    }
  }

  (int, Map<String, dynamic>) _requestMode(String target) {
    // Faithful subset of ModeController._ALLOWED + request_mode's reset rule.
    if (target == mode) {
      return (200, {'ok': true, 'mode': mode});
    }
    const motionModes = {'MANUAL', 'AUTONOMOUS'};
    const fromIdle = {'MANUAL'};
    const fromManual = {'IDLE', 'AUTONOMOUS'};
    const fromAutonomous = {'IDLE', 'MANUAL'};
    const fromStopped = {'IDLE'}; // SAFETY_STOP / ERROR -> reset to IDLE only

    late Set<String> allowed;
    if (mode == 'IDLE') allowed = fromIdle;
    if (mode == 'MANUAL') allowed = fromManual;
    if (mode == 'AUTONOMOUS') allowed = fromAutonomous;
    if (mode == 'SAFETY_STOP' || mode == 'ERROR') allowed = fromStopped;

    if (!allowed.contains(target)) {
      return (400, {'ok': false, 'error': 'illegal mode transition $mode -> $target'});
    }
    mode = target;
    motionModes.contains(target); // no-op, keeps the two-set around
    return (200, {'ok': true, 'mode': mode});
  }

  (int, Map<String, dynamic>) _motion(String name, Map<String, dynamic> cmd) {
    if (mode != 'MANUAL' && mode != 'AUTONOMOUS') {
      return (400, {'ok': false, 'error': 'motion not allowed in mode $mode'});
    }
    final speed = int.tryParse((cmd['speed'] ?? _motionDefaults[name]).toString());
    if (speed == null || speed < 1 || speed > maxSpeed) {
      return (400, {'ok': false, 'error': 'speed ${cmd['speed']} out of range [1, $maxSpeed]'});
    }
    return (200, {'ok': true, 'cmd': name});
  }

  (int, Map<String, dynamic>) _get(String path) {
    switch (path) {
      case '/health':
        return (200, {
          'ok': true,
          'status': 'OK',
          'simulated': true,
          'connected': true,
          'mode': mode,
          'serving': true,
          'uptime': 12.3,
          'schema_version': '1.0',
          'software_version': '0.1.0',
        });

      case '/status':
        return (200, {
          'mode': mode,
          'connected': true,
          'left_speed': 0,
          'right_speed': 0,
          'front_cm': frontCm,
          'left_cm': leftCm,
          'right_cm': rightCm,
          'rear_cm': rearCm,
          'last_error': null,
          'is_moving': false,
        });

      case '/applications/state':
        return (200, {
          'version': 1,
          'count': 2,
          'categories': ['monitoring', 'reference'],
          'applications': [
            {
              'id': 'command_center',
              'name': 'AMR Command Center',
              'description': 'The primary operator console.',
              'category': 'monitoring',
              'platforms': ['web'],
              'url': '/command-center',
              'api_base': '/dashboard/state',
              'launch_command': 'python -m amr.main --mock --web',
              'icon': 'console',
              'read_only': true,
              'requires_robot': true,
              'requires_camera': false,
              'requires_hardware': false,
              'declared_status': 'AVAILABLE',
              'status': 'MOCK',
              'reason': 'mock-robot',
              'detail': 'Working against the simulated robot.',
            },
            {
              'id': 'applications_hub',
              'name': 'Applications Hub',
              'description': 'Directory of every interface.',
              'category': 'reference',
              'platforms': ['web'],
              'url': '/applications',
              'api_base': '/applications/state',
              'launch_command': 'python -m amr.main --mock --web',
              'icon': 'grid',
              'read_only': true,
              'requires_robot': false,
              'requires_camera': false,
              'requires_hardware': false,
              'declared_status': 'AVAILABLE',
              'status': 'MOCK',
              'reason': 'mock-robot',
              'detail': 'Working against the simulated robot.',
            },
          ],
        });

      case '/telemetry':
        return (200, {
          'schema_version': '1.0',
          'simulated': true,
          'source': 'SIMULATION',
          'mode': mode,
          'robot_id': 'amr-robot',
          'battery': {
            'percentage': batteryPercentage,
            'voltage': batteryVoltage,
            'charging': null,
            'source': 'SIMULATION',
          },
          'sensors': {
            'front_cm': frontCm,
            'left_cm': leftCm,
            'right_cm': rightCm,
            'rear_cm': rearCm,
            'source': 'SIMULATION',
          },
          'velocity': {'linear': speedMps, 'angular': null, 'moving': false, 'source': 'SIMULATION'},
          'safety': {
            'action': 'PROCEED',
            'state': 'IDLE',
            'emergency_stop': mode == 'SAFETY_STOP',
            'reasons': <Object>[],
            'source': 'SIMULATION',
          },
          'system': {
            'robot_id': 'amr-robot',
            'connected': true,
            'mode': mode,
            'last_error': null,
            'simulated': true,
            'source': 'SIMULATION',
            'schema_version': '1.0',
            'software_version': '0.1.0',
            'uptime': 12.3,
          },
        });

      default:
        return (404, {'error': 'not found'});
    }
  }
}