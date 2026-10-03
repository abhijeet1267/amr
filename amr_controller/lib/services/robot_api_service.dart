// The single HTTP client for the robot.
//
// Every request goes through here so timeouts, unreachable-host handling and
// the base-URL join live in exactly one place. The robot's server speaks plain
// JSON over stdlib HTTP with no auth (LAN, single operator) — this client
// mirrors that and adds nothing.
//
// Verb surface (all verified against raspberry_pi/amr/web/server.py):
//   GET  /applications/state   -> registry payload
//   GET  /telemetry            -> full telemetry snapshot
//   GET  /health               -> liveness + reachability
//   GET  /status               -> raw robot snapshot (mode/speeds/ultrasonic)
//   POST /command {cmd, ...}   -> {ok, ...} (motion, stop, estop, mode)
library;

import 'dart:convert';

import 'package:http/http.dart' as http;

/// Raised when the robot is unreachable or an HTTP error came back. Carries a
/// human-readable reason so the UI can print *why* without parsing prose.
class RobotApiException implements Exception {
  const RobotApiException(this.message, {this.statusCode});
  final String message;
  final int? statusCode;

  @override
  String toString() => message;
}

class RobotApiService {
  RobotApiService({
    this.timeout = const Duration(seconds: 4),
  });

  final Duration timeout;

  /// Host with or without a scheme/path; normalised to a clean origin.
  String _normaliseOrigin(String host) {
    var h = host.trim();
    if (h.isEmpty) return '';
    if (!h.startsWith('http://') && !h.startsWith('https://')) {
      h = 'http://$h';
    }
    while (h.endsWith('/')) {
      h = h.substring(0, h.length - 1);
    }
    return h;
  }

  Uri _uri(String origin, String path) => Uri.parse('$origin$path');

  Future<Map<String, dynamic>> _getJson(
    String origin,
    String path,
  ) async {
    final client = http.Client();
    try {
      final res = await client
          .get(_uri(origin, path))
          .timeout(timeout);
      if (res.statusCode != 200) {
        throw RobotApiException(
          'HTTP ${res.statusCode} from $path',
          statusCode: res.statusCode,
        );
      }
      final decoded = jsonDecode(res.body);
      if (decoded is! Map<String, dynamic>) {
        throw RobotApiException('Unexpected response shape from $path');
      }
      return decoded;
    } on RobotApiException {
      rethrow;
    } catch (e) {
      throw RobotApiException('Cannot reach robot at $origin: $e');
    } finally {
      client.close();
    }
  }

  Future<Map<String, dynamic>> _postJson(
    String origin,
    String path,
    Map<String, dynamic> body,
  ) async {
    final client = http.Client();
    try {
      final res = await client
          .post(
            _uri(origin, path),
            headers: {'Content-Type': 'application/json'},
            body: jsonEncode(body),
          )
          .timeout(timeout);
      final decoded = res.body.isEmpty ? <String, dynamic>{} : jsonDecode(res.body);
      if (decoded is! Map<String, dynamic>) {
        throw RobotApiException('Unexpected response shape from $path');
      }
      // The robot uses HTTP status as part of the command contract (400 for a
      // veto / bad payload). Surface both the {ok} flag and the status.
      if (res.statusCode >= 400 || decoded['ok'] == false) {
        throw RobotApiException(
          decoded['error'] as String? ??
              'command refused (HTTP ${res.statusCode})',
          statusCode: res.statusCode,
        );
      }
      return decoded;
    } on RobotApiException {
      rethrow;
    } catch (e) {
      throw RobotApiException('Cannot reach robot at $origin: $e');
    } finally {
      client.close();
    }
  }

  Future<Map<String, dynamic>> fetchApplications(String origin) =>
      _getJson(origin, '/applications/state');

  Future<Map<String, dynamic>> fetchTelemetry(String origin) =>
      _getJson(origin, '/telemetry');

  Future<Map<String, dynamic>> fetchHealth(String origin) =>
      _getJson(origin, '/health');

  Future<Map<String, dynamic>> fetchStatus(String origin) =>
      _getJson(origin, '/status');

  /// Motion and safety commands. Returns the robot's `{ok, ...}` body on
  /// success and throws [RobotApiException] on refusal.
  Future<Map<String, dynamic>> sendCommand(
    String origin,
    String cmd, {
    int? speed,
    String? mode,
  }) {
    final body = <String, dynamic>{'cmd': cmd};
    if (speed != null) body['speed'] = speed;
    if (mode != null) body['mode'] = mode;
    return _postJson(origin, '/command', body);
  }
}