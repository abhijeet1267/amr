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

/// One endpoint probe from the setup wizard's connection test.
///
/// `required` marks whether the app is usable when this endpoint is down: a
/// missing camera is not fatal, a missing `/health` is. The wizard probes each
/// endpoint individually so an operator is told *which* part answered.
class EndpointCheck {
  const EndpointCheck({
    required this.name,
    required this.path,
    required this.ok,
    required this.required,
    required this.detail,
    this.latencyMs,
    this.fix,
  });

  final String name;
  final String path;
  final bool ok;
  final bool required;
  final String detail;
  final int? latencyMs;

  /// What to do when this check fails (null when it cannot fail usefully).
  final String? fix;
}

/// How serious a preflight finding is. `fatal` blocks driving.
enum PreflightSeverity { info, warning, fatal }

/// A precondition for safe operation, evaluated from the live snapshot.
class PreflightItem {
  const PreflightItem(this.severity, this.title, this.detail, {this.fix});
  final PreflightSeverity severity;
  final String title;
  final String detail;
  final String? fix;
}

/// One endpoint the wizard probes, with the operator-facing fix text.
class _Probe {
  const _Probe(this.name, this.path, {required this.required, this.fix});
  final String name;
  final String path;
  final bool required;
  final String? fix;
}

class RobotProvider extends ChangeNotifier {
  RobotProvider({RobotApiService? api}) : _api = api ?? RobotApiService();

  final RobotApiService _api;

  static const _prefsHostKey = 'amr.host';
  static const _prefsAutoReconnectKey = 'amr.auto_reconnect';
  static const _prefsSimKey = 'amr.simulation';
  static const _prefsSetupKey = 'amr.setup_complete';

  /// The endpoints the setup wizard probes, in the order it shows them.
  /// `required: true` means "the app is not usable without this".
  static const _probes = <_Probe>[
    _Probe('Robot liveness', '/health', required: true,
        fix: 'Start the robot server: python -m amr.main --web'),
    _Probe('Robot status', '/status', required: true,
        fix: 'The server answered /health but not /status — check the Pi logs.'),
    _Probe('Telemetry', '/telemetry', required: true,
        fix: 'Telemetry unavailable — check raspberry_pi/logs/amr.log on the Pi.'),
    _Probe('Applications', '/applications/state', required: false,
        fix: 'Is this actually the AMR server? Another service may hold the port.'),
    _Probe('Warehouse map', '/map', required: false,
        fix: 'Map unavailable — config/warehouse.yaml may be disabled.'),
    _Probe('Heat map', '/heatmap', required: false,
        fix: 'Heat map unavailable — expected if no warehouse geometry is set.'),
    _Probe('Camera', '/camera/status', required: false,
        fix: 'No camera. The app still works; attach one to use the Camera screen.'),
    _Probe('Connectivity', '/connectivity', required: false,
        fix: 'Host connectivity probe unavailable.'),
    _Probe('Hazard layer', '/hazard', required: false,
        fix: 'Hazard layer not attached — expected when it is disabled.'),
  ];

  /// Setup wizard: per-endpoint results. Empty until a test is run.
  List<EndpointCheck> diagnostics = const [];
  bool diagnosticsRunning = false;

  /// Setup wizard: true once the operator finished (or skipped) first-run setup.
  bool setupComplete = false;

  /// True once the saved connection has been read, so the root gate knows
  /// whether `setupComplete` is meaningful yet (it is false until then).
  bool setupLoaded = false;

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
  HeatmapState? heatmap;
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
    setupComplete = prefs.getBool(_prefsSetupKey) ?? false;
    setupLoaded = true;
    notifyListeners();
  }

  /// Finish first-run setup so the console becomes the home screen.
  Future<void> markSetupComplete() async {
    setupComplete = true;
    final prefs = await SharedPreferences.getInstance();
    await prefs.setBool(_prefsSetupKey, true);
    notifyListeners();
  }

  /// Re-open the wizard on the next launch (used by the Connection screen's
  /// "Run setup again" action).
  Future<void> resetSetup() async {
    setupComplete = false;
    final prefs = await SharedPreferences.getInstance();
    await prefs.setBool(_prefsSetupKey, false);
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
        _api.fetchHeatmap(_origin),
      ]);
      if (_disposed) return false;
      telemetry = TelemetryState.fromJson(results[0]);
      registry = RegistryPayload.fromJson(results[1]);
      map = MapState.fromJson(results[2]);
      camera = CameraInfo.fromJson(results[3]);
      connectivity = ConnectivityInfo.fromJson(results[4]);
      heatmap = HeatmapState.fromJson(results[5]);
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
  // Setup wizard — connection test
  // ----------------------------------------------------------------------

  /// Probe every endpoint individually and record the result.
  ///
  /// Unlike [ping] (one all-or-nothing batch, correct for the polling loop),
  /// this streams each endpoint's outcome as it arrives, so the wizard can show
  /// exactly which part of the robot answered and give a fix for the rest.
  Future<void> runDiagnostics() async {
    if (diagnosticsRunning) return;
    diagnosticsRunning = true;
    diagnostics = const [];
    notifyListeners();

    final out = <EndpointCheck>[];
    for (final probe in _probes) {
      final sw = Stopwatch()..start();
      try {
        await _api.getJson(_origin, probe.path);
        out.add(EndpointCheck(
          name: probe.name,
          path: probe.path,
          ok: true,
          required: probe.required,
          detail: 'OK',
          latencyMs: sw.elapsedMilliseconds,
          fix: probe.fix,
        ));
      } on RobotApiException catch (e) {
        out.add(EndpointCheck(
          name: probe.name,
          path: probe.path,
          ok: false,
          required: probe.required,
          detail: e.message,
          fix: probe.fix,
        ));
      }
      diagnostics = List.unmodifiable(out);
      if (!_disposed) notifyListeners();
    }

    diagnosticsRunning = false;
    if (_disposed) return;

    // If the robot answered, seed the live feeds so the preflight step and the
    // sensor readings have real data to show.
    if (diagnostics.any((c) => c.ok && c.path == '/health')) {
      await ping();
    }
    notifyListeners();
  }

  /// True when every *required* endpoint answered.
  bool get coreEndpointsOk =>
      diagnostics.isNotEmpty && diagnostics.where((c) => c.required).every((c) => c.ok);

  // ----------------------------------------------------------------------
  // Setup wizard — preflight (fatal / warning preconditions)
  // ----------------------------------------------------------------------

  /// Evaluate the preconditions for safe operation from the current snapshot.
  ///
  /// Pure read — no network, no commands. A `fatal` finding must block driving;
  /// the wizard refuses to advance while one exists.
  List<PreflightItem> preflight() {
    final out = <PreflightItem>[];

    if (simulation) {
      out.add(const PreflightItem(
        PreflightSeverity.warning,
        'SIMULATION MODE',
        'No real robot is connected. Every command is blocked by design.',
        fix: 'Turn off simulation in Connection and enter the robot\'s IP address.',
      ));
      return out;
    }

    if (connection != RobotConnectionState.connected) {
      out.add(const PreflightItem(
        PreflightSeverity.fatal,
        'NO ROBOT CONNECTION',
        'The app cannot reach the robot.',
        fix: 'Run the connection test. Confirm the robot is powered and on the '
            'same network, then check the host and port.',
      ));
      // Nothing below can be evaluated without a link.
      return out;
    }

    final t = telemetry;
    if (t != null) {
      if (!t.connected) {
        out.add(const PreflightItem(
          PreflightSeverity.fatal,
          'PI ↔ ARDUINO LINK DOWN',
          'The Raspberry Pi cannot talk to the Arduino over serial.',
          fix: 'Check the USB cable and the port in config/serial.yaml '
              '(see tools/health_check.sh).',
        ));
      }
      if (t.emergencyStop) {
        out.add(const PreflightItem(
          PreflightSeverity.fatal,
          'E-STOP ACTIVE',
          'Motion is disabled until the E-STOP is cleared.',
          fix: 'Clear the E-STOP on the Teleop screen before driving.',
        ));
      }
      final front = t.frontCm;
      if (front != null && front >= 0 && front < 30) {
        out.add(PreflightItem(
          PreflightSeverity.fatal,
          'OBSTACLE TOO CLOSE',
          'Front sensor reads $front cm.',
          fix: 'Clear the space in front of the robot before moving.',
        ));
      }
      final battery = t.batteryPercentage;
      if (battery != null && battery < 20) {
        out.add(PreflightItem(
          PreflightSeverity.fatal,
          'BATTERY CRITICAL',
          '${battery.round()}% remaining.',
          fix: 'Charge the robot before driving.',
        ));
      } else if (battery != null && battery < 30) {
        out.add(PreflightItem(
          PreflightSeverity.warning,
          'LOW BATTERY',
          '${battery.round()}% remaining.',
          fix: 'Consider charging soon.',
        ));
      }
      final mode = t.mode;
      if (mode != null && mode != 'IDLE' && mode != 'MANUAL') {
        out.add(PreflightItem(
          PreflightSeverity.warning,
          'ROBOT NOT IN MANUAL',
          'Mode is $mode.',
          fix: 'Switch to MANUAL before teleoperating.',
        ));
      }
    }

    final cam = camera;
    if (cam != null && !cam.isLive) {
      out.add(const PreflightItem(
        PreflightSeverity.warning,
        'CAMERA OFFLINE',
        'No live camera frames.',
        fix: 'The app works without a camera; attach one to use the Camera screen.',
      ));
    }
    if (latencyMs != null && latencyMs! > 500) {
      out.add(PreflightItem(
        PreflightSeverity.warning,
        'HIGH LATENCY',
        '$latencyMs ms round trip.',
        fix: 'Move closer to the robot\'s network or reduce Wi-Fi congestion.',
      ));
    }

    if (out.isEmpty) {
      out.add(const PreflightItem(
        PreflightSeverity.info,
        'ALL CHECKS PASSED',
        'The robot is connected and ready to drive.',
      ));
    }
    return out;
  }

  /// Convenience for the wizard: the fatal findings only.
  List<PreflightItem> fatalPreflight() =>
      preflight().where((i) => i.severity == PreflightSeverity.fatal).toList();


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
        _api.fetchHeatmap(_origin),
      ]);
      if (_disposed) return;
      telemetry = TelemetryState.fromJson(results[0]);
      registry = RegistryPayload.fromJson(results[1]);
      map = MapState.fromJson(results[2]);
      camera = CameraInfo.fromJson(results[3]);
      connectivity = ConnectivityInfo.fromJson(results[4]);
      heatmap = HeatmapState.fromJson(results[5]);
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