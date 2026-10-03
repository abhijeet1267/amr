// Data models — the shape of the robot's JSON, mirrored so the UI never has to
// poke a raw Map<String, dynamic>.
//
// Field names and nullability follow the robot's actual contract
// (raspberry_pi/amr/apps/registry.py `Application.to_dict` +
// `resolve_status`, and the C7 telemetry `types.py` sections). Where the robot
// deliberately reports `null` (no battery sensor, no temperature sensor), these
// models keep `null` instead of inventing a 0 — "not measured" is a different
// fact from "zero", and the UI says so.
library;

/// One entry of `GET /applications/state`.
class AppState {
  const AppState({
    required this.id,
    required this.name,
    required this.description,
    required this.category,
    required this.platforms,
    required this.status,
    this.url,
    this.apiBase,
    this.launchCommand,
    this.icon,
    required this.readOnly,
    required this.requiresRobot,
    required this.requiresCamera,
    required this.requiresHardware,
    this.reason,
    this.detail,
  });

  final String id;
  final String name;
  final String description;
  final String category;
  final List<String> platforms;

  /// The status the runtime reports *now* — never better than `declared`.
  final String status;
  final String? url;
  final String? apiBase;
  final String? launchCommand;
  final String? icon;
  final bool readOnly;
  final bool requiresRobot;
  final bool requiresCamera;
  final bool requiresHardware;
  final String? reason;
  final String? detail;

  bool get hasInterface => url != null && url!.isNotEmpty;

  factory AppState.fromJson(Map<String, dynamic> json) {
    return AppState(
      id: json['id'] as String? ?? '',
      name: json['name'] as String? ?? json['id'] as String? ?? '',
      description: json['description'] as String? ?? '',
      category: json['category'] as String? ?? '',
      platforms: (json['platforms'] as List<dynamic>? ?? const [])
          .map((e) => e.toString())
          .toList(),
      status: json['status'] as String? ?? 'UNKNOWN',
      url: json['url'] as String?,
      apiBase: json['api_base'] as String?,
      launchCommand: json['launch_command'] as String?,
      icon: json['icon'] as String?,
      readOnly: json['read_only'] as bool? ?? true,
      requiresRobot: json['requires_robot'] as bool? ?? false,
      requiresCamera: json['requires_camera'] as bool? ?? false,
      requiresHardware: json['requires_hardware'] as bool? ?? false,
      reason: json['reason'] as String?,
      detail: json['detail'] as String?,
    );
  }
}

/// The whole `GET /applications/state` document.
class RegistryPayload {
  const RegistryPayload({
    required this.applications,
    required this.categories,
    this.count,
  });

  final List<AppState> applications;
  final List<String> categories;
  final int? count;

  factory RegistryPayload.fromJson(Map<String, dynamic> json) {
    return RegistryPayload(
      applications: (json['applications'] as List<dynamic>? ?? const [])
          .map((e) => AppState.fromJson(e as Map<String, dynamic>))
          .toList(),
      categories: (json['categories'] as List<dynamic>? ?? const [])
          .map((e) => e.toString())
          .toList(),
      count: json['count'] as int?,
    );
  }
}

/// A `GET /telemetry` snapshot, parsed defensively: any section may be absent
/// if the robot predates it, so every getter tolerates a missing node.
class TelemetryState {
  const TelemetryState({
    this.robotId,
    this.connected = false,
    this.mode,
    this.simulated = false,
    this.batteryPercentage,
    this.batteryVoltage,
    this.frontCm,
    this.leftCm,
    this.rightCm,
    this.rearCm,
    this.speedMps,
    this.safetyAction,
    this.emergencyStop = false,
    this.lastError,
  });

  final String? robotId;
  final bool connected;
  final String? mode;
  final bool simulated;
  final double? batteryPercentage;
  final double? batteryVoltage;
  final int? frontCm;
  final int? leftCm;
  final int? rightCm;
  final int? rearCm;
  final double? speedMps;
  final String? safetyAction;
  final bool emergencyStop;
  final String? lastError;

  factory TelemetryState.fromJson(Map<String, dynamic> json) {
    // system.* is the single source of truth for identity/mode; top-level
    // mirror keys exist but the section's own block is what to read.
    final system = (json['system'] as Map<String, dynamic>?) ?? const {};
    final battery = (json['battery'] as Map<String, dynamic>?) ?? const {};
    final sensors = (json['sensors'] as Map<String, dynamic>?) ?? const {};
    final velocity = (json['velocity'] as Map<String, dynamic>?) ?? const {};
    final safety = (json['safety'] as Map<String, dynamic>?) ?? const {};

    double? toDouble(dynamic v) {
      if (v == null) return null;
      if (v is num) return v.toDouble();
      return double.tryParse(v.toString());
    }

    int? toInt(dynamic v) {
      if (v == null) return null;
      if (v is int) return v;
      if (v is num) return v.round();
      return int.tryParse(v.toString());
    }

    return TelemetryState(
      robotId: system['robot_id'] as String?,
      connected: system['connected'] as bool? ?? false,
      mode: system['mode'] as String?,
      simulated:
          (system['simulated'] as bool?) ?? (json['simulated'] as bool?) ?? false,
      batteryPercentage: toDouble(battery['percentage']),
      batteryVoltage: toDouble(battery['voltage']),
      frontCm: toInt(sensors['front_cm']),
      leftCm: toInt(sensors['left_cm']),
      rightCm: toInt(sensors['right_cm']),
      rearCm: toInt(sensors['rear_cm']),
      speedMps: toDouble(velocity['linear']),
      safetyAction: safety['action'] as String?,
      emergencyStop: safety['emergency_stop'] as bool? ?? false,
      lastError: system['last_error'] as String?,
    );
  }
}