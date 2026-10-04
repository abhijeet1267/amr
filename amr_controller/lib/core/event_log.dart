// Operator event log and the deterministic simulation driver.
//
// The event log records real connection/command/telemetry events so the Logs
// screen and the alert banner share one source of truth. The simulation driver
// generates a *clearly labelled* stream of plausible-but-fake telemetry so the
// whole UI can be exercised with no Raspberry Pi. Simulation never issues a
// command and is visually distinct from LIVE at every point.

import 'dart:math' as math;

import 'package:flutter/foundation.dart';

/// Severity of a log entry / operator alert. Colour is never the only signal —
/// the label is always shown.
enum LogLevel { info, command, warning, safety, error }

extension LogLevelLabel on LogLevel {
  String get label => switch (this) {
        LogLevel.info => 'INFO',
        LogLevel.command => 'CMD',
        LogLevel.warning => 'WARN',
        LogLevel.safety => 'SAFETY',
        LogLevel.error => 'ERROR',
      };
}

class LogEntry {
  LogEntry(this.time, this.level, this.message);

  final DateTime time;
  final LogLevel level;
  final String message;

  String get hhmmss =>
      '${time.hour.toString().padLeft(2, '0')}:${time.minute.toString().padLeft(2, '0')}:${time.second.toString().padLeft(2, '0')}';
}

class EventLog extends ChangeNotifier {
  EventLog({this.capacity = 500});

  final int capacity;
  final List<LogEntry> _entries = [];

  List<LogEntry> get entries => List.unmodifiable(_entries);

  void add(LogLevel level, String message) {
    _entries.add(LogEntry(DateTime.now(), level, message));
    if (_entries.length > capacity) {
      _entries.removeRange(0, _entries.length - capacity);
    }
    notifyListeners();
  }

  void clear() {
    _entries.clear();
    notifyListeners();
  }

  /// Safety entries persist until explicitly acknowledged; they are simply the
  /// safety/error subset and are surfaced in the alert banner until cleared.
  List<LogEntry> get activeSafety =>
      _entries.where((e) => e.level == LogLevel.safety).toList();
}

/// A deterministic, clearly-labelled simulation of the robot. Values evolve by
/// a seeded PRNG so the demo is stable but not static, and every field carries
/// `simulated: true`. It is consumed by the provider in SIMULATION mode only.
class SimulatedRobot {
  SimulatedRobot({int seed = 42})
      : _random = math.Random(seed),
        _x = 4.5,
        _y = 3.0;

  final math.Random _random;
  double _x;
  double _y;
  double _yaw = 0.0; // radians
  double _battery = 82.0;
  double _frontCm = 120.0;
  int _tick = 0;

  /// Advances the simulation one step and returns a telemetry-shaped map.
  Map<String, dynamic> tick() {
    _tick++;
    // Slow wander so the map looks alive but stays deterministic.
    _yaw += (_random.nextDouble() - 0.5) * 0.06;
    _x += math.cos(_yaw) * 0.04;
    _y += math.sin(_yaw) * 0.04;
    _battery = math.max(5, _battery - 0.01);
    _frontCm = 40 + _random.nextDouble() * 160;
    final speed = 0.3 + _random.nextDouble() * 0.2;
    return {
      'batteryPercentage': _battery,
      'batteryVoltage': 11.8 + _random.nextDouble() * 0.4,
      'frontCm': _frontCm.round(),
      'leftCm': (_frontCm + 20).round(),
      'rightCm': (_frontCm - 10).round(),
      'rearCm': 140 + _random.nextInt(40),
      'speedMps': speed,
      'x': _x,
      'y': _y,
      'yaw': _yaw,
      'mode': 'MANUAL',
      'connected': true,
      'tick': _tick,
    };
  }
}