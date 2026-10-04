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

import '../core/event_log.dart';
import '../core/format.dart';
import '../models/app_state.dart';
import '../models/robot_data.dart';
import '../services/robot_api_service.dart';

enum RobotConnectionState { disconnected, connecting, connected, error }

/// A non-intrusive operator alert derived from live telemetry. Colour is never
/// the only signal — the message is always shown as text.
enum AlertSeverity { info, warning, critical }

class OperatorAlert {
  const OperatorAlert(this.severity, this.message);
  final AlertSeverity severity;
  final String message;
}

class RobotProvider extends ChangeNotifier {
  RobotProvider({RobotApiService? api}) : _api = api ?? RobotApiService();

  final RobotApiService _api;

  static const _prefsHostKey = 'amr.host';
  static const _prefsAutoReconnectKey = 'amr.auto_reconnect';
  static const _prefsSimKey = 'amr.simulation';

  String host = '';
  RobotConnectionState connection = RobotConnectionState.disconnected;
  String connectionDetail = '';
  bool autoReconnect = true;

  /// When true, no network is used and deterministic simulated telemetry fills
  /// the dashboard/map/sensors. Clearly labelled everywhere; never issues a
  /// command.
  bool simulation = false;

  RegistryPayload? registry;
  TelemetryState? telemetry;
  MapState? map;
  CameraInfo? camera;
  CameraOverlay? cameraOverlay;
  List<int>? cameraFrameBytes;
  ConnectivityInfo? connectivity;
  Map<String, dynamic>? hazard;

  final EventLog eventLog = EventLog();
  final SimulatedRobot _sim = SimulatedRobot();

  bool get isConnected => connection == RobotConnectionState.connected;

  bool _busy = false;
  bool get busy => _busy;

  String? lastError;
  bool lastCommandOk = false;
  String? lastCommandError;

  int? lastUpdateMs;

  /// Round-trip latency of the most recent health probe, in ms. Null until a
  /// live connection has actually measured it (never fabricated).
  int? latencyMs;

  /// Derived operator alerts (low battery, obstacle, E-STOP, camera, latency).
  /// Rebuilt after each poll; consumed by the shell's non-intrusive banner.
  List<OperatorAlert> alerts = const [];

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
    simulation = prefs.getBool(_prefsSimKey) ?? false;
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

  Future<void> setSimulation(bool value) async {
    simulation = value;
    final prefs = await SharedPreferences.getInstance();
    await prefs.setBool(_prefsSimKey, value);
    if (value) {
      // Enter simulation: no network, seed a deterministic fake snapshot.
      disconnect();
      connection = RobotConnectionState.connected;
      connectionDetail = 'simulation';
      _seedSimulation();
      _startPolling();
      eventLog.add(LogLevel.warning, 'SIMULATION MODE — no real robot control');
    } else {
      disconnect();
      _startPolling();
      eventLog.add(LogLevel.info, 'Simulation off');
    }
    notifyListeners();
  }

  void _seedSimulation() {
    final s = _sim.tick();
    telemetry = TelemetryState(
      robotId: 'amr-sim',
      connected: true,
      mode: 'MANUAL',
      simulated: true,
      batteryPercentage: s['batteryPercentage'] as double,
      batteryVoltage: s['batteryVoltage'] as double,
      frontCm: s['frontCm'] as int,
      leftCm: s['leftCm'] as int,
      rightCm: s['rightCm'] as int,
      rearCm: s['rearCm'] as int,
      speedMps: s['speedMps'] as double,
      safetyAction: 'PROCEED',
    );
    map = _simMap(s);
    lastUpdateMs = DateTime.now().millisecondsSinceEpoch;
  }

  MapState _simMap(Map<String, dynamic> s) => MapState(
        source: 'SIMULATION',
        units: 'metres',
        robot: MapRobot(
          x: s['x'] as double,
          y: s['y'] as double,
          yaw: s['yaw'] as double,
          source: 'SIMULATION',
        ),
        goal: null,
        route: const [],
        path: const [],
        hazards: const [],
        zones: const [],
        waypoints: const [
          MapWaypoint(name: 'Dock', x: 0.5, y: 0.5, theta: 0, source: 'SIMULATION'),
          MapWaypoint(name: 'Shelf A', x: 4.0, y: 1.0, theta: 0, source: 'SIMULATION'),
          MapWaypoint(name: 'Shelf B', x: 7.0, y: 3.0, theta: 0, source: 'SIMULATION'),
          MapWaypoint(name: 'Charging', x: 2.0, y: 6.0, theta: 0, source: 'SIMULATION'),
        ],
        navigationState: 'IDLE',
      );

  void _simTick() {
    if (connection != RobotConnectionState.connected || !simulation) return;
    final s = _sim.tick();
    telemetry = TelemetryState(
      robotId: 'amr-sim',
      connected: true,
      mode: 'MANUAL',
      simulated: true,
      batteryPercentage: s['batteryPercentage'] as double,
      batteryVoltage: s['batteryVoltage'] as double,
      frontCm: s['frontCm'] as int,
      leftCm: s['leftCm'] as int,
      rightCm: s['rightCm'] as int,
      rearCm: s['rearCm'] as int,
      speedMps: s['speedMps'] as double,
      safetyAction: 'PROCEED',
    );
    map = _simMap(s);
    lastUpdateMs = DateTime.now().millisecondsSinceEpoch;
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
      final sw = Stopwatch()..start();
      final health = await _api.fetchHealth(_origin);
      latencyMs = sw.elapsedMilliseconds;
      connection = RobotConnectionState.connected;
      connectionDetail = _describeHealth(health);
      lastError = null;

      // Seed every feed in parallel, THEN notify once (single broadcast, not
      // five — avoids five full rebuilds on connect).
      final results = await Future.wait([
        _api.fetchTelemetry(_origin),
        _api.fetchApplications(_origin),
        _api.fetchMap(_origin),
        _api.fetchCameraStatus(_origin),
        _api.fetchConnectivity(_origin),
      ]);
      if (_disposed) return false;
      telemetry = TelemetryState.fromJson(results[0]);
      registry = RegistryPayload.fromJson(results[1]);
      map = MapState.fromJson(results[2]);
      camera = CameraInfo.fromJson(results[3]);
      connectivity = ConnectivityInfo.fromJson(results[4]);
      lastUpdateMs = DateTime.now().millisecondsSinceEpoch;
      _rebuildAlerts();
      notifyListeners();

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
    if (simulation) {
      _simTick();
      return;
    }
    try {
      // Fetch all feeds first, THEN notify once — the previous split of five
      // notifyListeners() per poll caused five full broadcasts per tick.
      final results = await Future.wait([
        _api.fetchTelemetry(_origin),
        _api.fetchApplications(_origin),
        _api.fetchMap(_origin),
        _api.fetchCameraStatus(_origin),
        _api.fetchConnectivity(_origin),
      ]);
      if (_disposed) return;
      telemetry = TelemetryState.fromJson(results[0]);
      registry = RegistryPayload.fromJson(results[1]);
      map = MapState.fromJson(results[2]);
      camera = CameraInfo.fromJson(results[3]);
      connectivity = ConnectivityInfo.fromJson(results[4]);
      lastUpdateMs = DateTime.now().millisecondsSinceEpoch;
      _rebuildAlerts();
      if (connection != RobotConnectionState.connected) {
        connection = RobotConnectionState.connected;
        lastError = null;
      }
      notifyListeners();
    } on RobotApiException catch (e) {
      if (_disposed) return;
      // A dropped connection should not hammer the network with retries if the
      // operator asked for auto-reconnect: schedule one gentle re-probe and
      // back off until it succeeds.
      _markDisconnected(e.message);
      if (autoReconnect) _scheduleReconnect();
    }
  }

  /// Recompute the operator alert list from the current snapshot. Pure read —
  /// no commands, no network.
  void _rebuildAlerts() {
    final t = telemetry;
    final out = <OperatorAlert>[];
    if (t == null) return;
    final battery = t.batteryPercentage;
    if (battery != null && battery < 20) {
      out.add(OperatorAlert(AlertSeverity.critical, 'LOW BATTERY — ${battery.round()}%'));
    } else if (battery != null && battery < 30) {
      out.add(const OperatorAlert(AlertSeverity.warning, 'Battery below 30%'));
    }
    final front = t.frontCm;
    if (front != null && front < 30) {
      out.add(OperatorAlert(AlertSeverity.critical, 'OBSTACLE TOO CLOSE — $front cm'));
    }
    if (t.emergencyStop) {
      out.add(const OperatorAlert(AlertSeverity.critical, 'E-STOP ACTIVE — motion disabled'));
    }
    final cam = camera;
    if (cam != null && !cam.isLive) {
      out.add(const OperatorAlert(AlertSeverity.warning, 'CAMERA OFFLINE'));
    }
    if (latencyMs != null && latencyMs! > 500) {
      out.add(OperatorAlert(AlertSeverity.warning, 'HIGH LATENCY — ${fmtLatency(latencyMs)}'));
    }
    alerts = out;
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
  // Data refreshes (silent — callers notify once after the batch)
  // ----------------------------------------------------------------------
  Future<void> _refreshTelemetry() async {
    final json = await _api.fetchTelemetry(_origin);
    if (_disposed) return;
    telemetry = TelemetryState.fromJson(json);
    _rebuildAlerts();
  }

  /// Fetch the latest camera snapshot + vision overlay (on demand, not every
  /// poll — the backend serves the latest cached frame and boxes).
  Future<void> refreshCameraFrame() async {
    if (simulation) return;
    try {
      cameraFrameBytes = await _api.fetchCameraFrame(_origin);
      cameraOverlay = CameraOverlay.fromJson(
          await _api.fetchCameraOverlay(_origin));
    } on RobotApiException {
      cameraFrameBytes = null;
      cameraOverlay = null;
    }
    if (!_disposed) notifyListeners();
  }

  // ----------------------------------------------------------------------
  // Commands
  // ----------------------------------------------------------------------
  Future<bool> command(String cmd, {int? speed, String? mode}) async {
    if (simulation) {
      // Simulation never issues a command — this is the gate that guarantees
      // "SIMULATION — NO REAL ROBOT CONTROL".
      lastCommandOk = false;
      lastCommandError = 'blocked: simulation mode issues no commands';
      eventLog.add(LogLevel.warning, 'command blocked in simulation: $cmd');
      notifyListeners();
      return false;
    }
    if (cmd == 'estop') {
      eventLog.add(LogLevel.safety, 'E-STOP sent');
    } else if (cmd == 'stop') {
      eventLog.add(LogLevel.command, 'STOP');
    } else if (cmd == 'mode') {
      eventLog.add(LogLevel.info, 'mode -> ${mode ?? ''}');
    } else {
      eventLog.add(LogLevel.command, '${cmd.toUpperCase()}${speed != null ? ' speed=$speed' : ''}');
    }

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
      eventLog.add(LogLevel.error, e.message);
      return false;
    } finally {
      _setBusy(false);
    }
  }

  void _setBusy(bool value) {
    if (_disposed) return;
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