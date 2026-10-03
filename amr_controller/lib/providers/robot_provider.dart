// State management for the whole client.
//
// A single ChangeNotifier holds connection state, the app registry, live
// telemetry, and the last polling/command outcome. Every screen reads it via
// Provider; nothing else talks to the network. Polling is a self-arming Timer
// so there is exactly one loop, not one per screen.
//
// Commands go through `command()` rather than the API client directly, so a
// motion/E-STOP attempt from anywhere ends up in one auditable path that
// updates `lastCommandOk`/`lastCommandError` and refreshes telemetry.
library;

import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../models/app_state.dart';
import '../services/robot_api_service.dart';

enum RobotConnectionState { disconnected, connecting, connected, error }

class RobotProvider extends ChangeNotifier {
  RobotProvider({RobotApiService? api}) : _api = api ?? RobotApiService();

  final RobotApiService _api;

  static const _prefsHostKey = 'amr.host';
  static const _prefsAutoReconnectKey = 'amr.auto_reconnect';

  String host = '';
  RobotConnectionState connection = RobotConnectionState.disconnected;
  String connectionDetail = '';
  bool autoReconnect = true;

  RegistryPayload? registry;
  TelemetryState? telemetry;

  bool get isConnected => connection == RobotConnectionState.connected;

  bool _busy = false;
  bool get busy => _busy;

  String? lastError;
  bool lastCommandOk = false;
  String? lastCommandError;

  Timer? _pollTimer;
  bool _disposed = false;

  /// The normalised origin used for requests. `host` is trimmed and given a
  /// scheme / de-trailing-slashed here, so every caller can build full URLs
  /// without re-deriving the rule.
  String get origin {
    var h = host.trim();
    if (h.isEmpty) return h;
    if (!h.startsWith('http://') && !h.startsWith('https://')) {
      h = 'http://$h';
    }
    while (h.endsWith('/')) {
      h = h.substring(0, h.length - 1);
    }
    return h;
  }

  String get _origin => origin;

  // ----------------------------------------------------------------------
  // Persistence
  // ----------------------------------------------------------------------
  Future<void> loadSavedConnection() async {
    final prefs = await SharedPreferences.getInstance();
    host = prefs.getString(_prefsHostKey) ?? '192.168.1.100:8080';
    autoReconnect = prefs.getBool(_prefsAutoReconnectKey) ?? true;
    notifyListeners();
  }

  Future<void> saveHost(String value) async {
    host = value.trim();
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(_prefsHostKey, value.trim());
    notifyListeners();
  }

  Future<void> setAutoReconnect(bool value) async {
    autoReconnect = value;
    final prefs = await SharedPreferences.getInstance();
    await prefs.setBool(_prefsAutoReconnectKey, value);
    notifyListeners();
  }

  // ----------------------------------------------------------------------
  // Connection lifecycle
  // ----------------------------------------------------------------------
  Future<bool> ping() async {
    _setBusy(true);
    connection = RobotConnectionState.connecting;
    connectionDetail = 'checking $host';
    notifyListeners();

    try {
      final health = await _api.fetchHealth(_origin);
      connection = RobotConnectionState.connected;
      connectionDetail = _describeHealth(health);
      lastError = null;

      // Seed both feeds immediately so the UI is live the moment the badge
      // flips to Connected.
      await Future.wait([
        _refreshRegistry(),
        _refreshTelemetry(),
      ]);

      _startPolling();
      return true;
    } on RobotApiException catch (e) {
      connection = RobotConnectionState.error;
      connectionDetail = e.message;
      lastError = e.message;
      _stopPolling();
      return false;
    } finally {
      _setBusy(false);
      notifyListeners();
    }
  }

  void disconnect() {
    _stopPolling();
    connection = RobotConnectionState.disconnected;
    connectionDetail = '';
    registry = null;
    telemetry = null;
    lastError = null;
    notifyListeners();
  }

  String _describeHealth(Map<String, dynamic> health) {
    final status = health['status'] as String? ?? 'OK';
    final simulated = health['simulated'] as bool? ?? false;
    final prefix = simulated ? 'simulated · ' : '';
    return '$prefix$status';
  }

  // ----------------------------------------------------------------------
  // Polling (1.5s, the spec's 1–2s band)
  // ----------------------------------------------------------------------
  void _startPolling() {
    _pollTimer?.cancel();
    _pollTimer = Timer.periodic(const Duration(milliseconds: 1500), (_) {
      if (!_disposed && connection == RobotConnectionState.connected) {
        _pollOnce();
      }
    });
  }

  void _stopPolling() {
    _pollTimer?.cancel();
    _pollTimer = null;
  }

  Future<void> _pollOnce() async {
    try {
      await Future.wait([_refreshTelemetry(), _refreshRegistry()]);
      if (_disposed) return;
      if (connection != RobotConnectionState.connected) {
        connection = RobotConnectionState.connected;
        lastError = null;
      }
    } on RobotApiException catch (e) {
      if (_disposed) return;
      // A dropped connection should not hammer the network with retries if the
      // operator asked for auto-reconnect: schedule one gentle re-probe and
      // back off until it succeeds.
      _markDisconnected(e.message);
      if (autoReconnect) _scheduleReconnect();
    }
  }

  void _markDisconnected(String detail) {
    connection = RobotConnectionState.error;
    connectionDetail = detail;
    lastError = detail;
    notifyListeners();
  }

  void _scheduleReconnect() {
    Future<void>.delayed(const Duration(seconds: 3), () async {
      if (_disposed || connection == RobotConnectionState.connected) return;
      await ping();
    });
  }

  // ----------------------------------------------------------------------
  // Data refreshes
  // ----------------------------------------------------------------------
  Future<void> _refreshRegistry() async {
    final json = await _api.fetchApplications(_origin);
    if (_disposed) return;
    registry = RegistryPayload.fromJson(json);
    notifyListeners();
  }

  Future<void> _refreshTelemetry() async {
    final json = await _api.fetchTelemetry(_origin);
    if (_disposed) return;
    telemetry = TelemetryState.fromJson(json);
    notifyListeners();
  }

  // ----------------------------------------------------------------------
  // Commands
  // ----------------------------------------------------------------------
  Future<bool> command(String cmd, {int? speed, String? mode}) async {
    _setBusy(true);
    lastCommandOk = false;
    lastCommandError = null;
    notifyListeners();
    try {
      await _api.sendCommand(_origin, cmd, speed: speed, mode: mode);
      lastCommandOk = true;
      // Pull telemetry once immediately so the motion/E-STOP is reflected
      // without waiting for the next poll tick.
      try {
        await _refreshTelemetry();
      } on RobotApiException {
        // Non-fatal: the command succeeded; the follow-up read can fail and the
        // next poll will reconcile it.
      }
      return true;
    } on RobotApiException catch (e) {
      lastCommandError = e.message;
      return false;
    } finally {
      _setBusy(false);
      notifyListeners();
    }
  }

  void _setBusy(bool value) {
    _busy = value;
    notifyListeners();
  }

  @override
  void dispose() {
    _disposed = true;
    _stopPolling();
    super.dispose();
  }
}