// Map & camera & connectivity models — the real payload shapes from the
// Raspberry Pi backend (`amr/map/snapshot.py`, `amr/net/connectivity.py`, and
// the `/camera/status` + `/camera/overlay` handlers in `amr/web/server.py`).
//
// Honesty rules match the backend: absent data is `null`, provenance is tagged
// (LIVE / SIMULATION / UNAVAILABLE), and "unavailable" is never a fabricated
// number.

class MapPoint {
  const MapPoint({required this.x, required this.y});

  final double x;
  final double y;

  factory MapPoint.fromJson(Map<String, dynamic> j) =>
      MapPoint(x: (j['x'] as num).toDouble(), y: (j['y'] as num).toDouble());
}

class MapWaypoint {
  const MapWaypoint({
    required this.name,
    required this.x,
    required this.y,
    required this.theta,
    required this.source,
  });

  final String name;
  final double x;
  final double y;
  final double theta;
  final String source;

  factory MapWaypoint.fromJson(Map<String, dynamic> j) => MapWaypoint(
        name: j['name'] as String? ?? '',
        x: (j['x'] as num?)?.toDouble() ?? 0,
        y: (j['y'] as num?)?.toDouble() ?? 0,
        theta: (j['theta'] as num?)?.toDouble() ?? 0,
        source: j['source'] as String? ?? 'UNAVAILABLE',
      );
}

class MapRobot {
  const MapRobot({
    required this.x,
    required this.y,
    required this.yaw,
    required this.source,
  });

  final double x;
  final double y;
  final double yaw;
  final String source;

  factory MapRobot.fromJson(Map<String, dynamic> j) => MapRobot(
        x: (j['x'] as num?)?.toDouble() ?? 0,
        y: (j['y'] as num?)?.toDouble() ?? 0,
        yaw: (j['yaw'] as num?)?.toDouble() ?? 0,
        source: j['source'] as String? ?? 'UNAVAILABLE',
      );
}

class MapGoal {
  const MapGoal({
    required this.name,
    required this.x,
    required this.y,
    required this.theta,
    required this.source,
  });

  final String name;
  final double x;
  final double y;
  final double theta;
  final String source;

  factory MapGoal.fromJson(Map<String, dynamic> j) => MapGoal(
        name: j['name'] as String? ?? '',
        x: (j['x'] as num?)?.toDouble() ?? 0,
        y: (j['y'] as num?)?.toDouble() ?? 0,
        theta: (j['theta'] as num?)?.toDouble() ?? 0,
        source: j['source'] as String? ?? 'UNAVAILABLE',
      );
}

class MapHazard {
  const MapHazard({
    required this.kind,
    required this.severity,
    required this.confidence,
    required this.x,
    required this.y,
    required this.source,
  });

  final String kind;
  final String? severity;
  final double? confidence;
  final double x;
  final double y;
  final String? source;

  factory MapHazard.fromJson(Map<String, dynamic> j) => MapHazard(
        kind: j['kind'] as String? ?? '',
        severity: j['severity'] as String?,
        confidence: (j['confidence'] as num?)?.toDouble(),
        x: (j['x'] as num?)?.toDouble() ?? 0,
        y: (j['y'] as num?)?.toDouble() ?? 0,
        source: j['source'] as String?,
      );
}

class MapZone {
  const MapZone({
    required this.name,
    required this.xMin,
    required this.xMax,
    required this.yMin,
    required this.yMax,
    this.kind,
    this.severity,
  });

  final String name;
  final double xMin;
  final double xMax;
  final double yMin;
  final double yMax;
  final String? kind;
  final String? severity;

  factory MapZone.fromJson(Map<String, dynamic> j) => MapZone(
        name: j['name'] as String? ?? '',
        xMin: (j['x_min'] as num?)?.toDouble() ?? 0,
        xMax: (j['x_max'] as num?)?.toDouble() ?? 0,
        yMin: (j['y_min'] as num?)?.toDouble() ?? 0,
        yMax: (j['y_max'] as num?)?.toDouble() ?? 0,
        kind: j['kind'] as String?,
        severity: j['severity'] as String?,
      );
}

class MapState {
  const MapState({
    required this.source,
    required this.units,
    required this.robot,
    required this.goal,
    required this.route,
    required this.path,
    required this.hazards,
    required this.zones,
    required this.waypoints,
    required this.navigationState,
    this.staticNote,
  });

  final String source;
  final String units;
  final MapRobot? robot;
  final MapGoal? goal;
  final List<MapPoint> route;
  final List<MapPoint> path;
  final List<MapHazard> hazards;
  final List<MapZone> zones;
  final List<MapWaypoint> waypoints;
  final String? navigationState;
  final String? staticNote;

  bool get isLive => source == 'LIVE';

  factory MapState.fromJson(Map<String, dynamic> j) {
    final warehouse = (j['warehouse'] as Map<String, dynamic>?) ?? const {};
    return MapState(
      source: j['source'] as String? ?? 'UNAVAILABLE',
      units: j['units'] as String? ?? 'metres',
      robot: j['robot'] == null ? null : MapRobot.fromJson(j['robot']),
      goal: j['goal'] == null ? null : MapGoal.fromJson(j['goal']),
      route: (j['route'] as List<dynamic>? ?? const [])
          .map((e) => MapPoint.fromJson(e as Map<String, dynamic>))
          .toList(),
      path: (j['path'] as List<dynamic>? ?? const [])
          .map((e) => MapPoint.fromJson(e as Map<String, dynamic>))
          .toList(),
      hazards: (j['hazards'] as List<dynamic>? ?? const [])
          .map((e) => MapHazard.fromJson(e as Map<String, dynamic>))
          .toList(),
      zones: (j['zones'] as List<dynamic>? ?? const [])
          .map((e) => MapZone.fromJson(e as Map<String, dynamic>))
          .toList(),
      waypoints: (warehouse['waypoints'] as List<dynamic>? ?? const [])
          .map((e) => MapWaypoint.fromJson(e as Map<String, dynamic>))
          .toList(),
      navigationState:
          (j['navigation'] as Map<String, dynamic>?)?['state'] as String?,
      staticNote: warehouse['note'] as String?,
    );
  }
}

class CameraInfo {
  const CameraInfo({
    required this.status,
    required this.source,
    required this.hasFrame,
    this.sourceName,
    this.width,
    this.height,
    this.format,
    this.frameId,
    this.timestamp,
    this.error,
  });

  final String status;
  final String source;
  final bool hasFrame;
  final String? sourceName;
  final int? width;
  final int? height;
  final String? format;
  final int? frameId;
  final double? timestamp;
  final String? error;

  bool get isLive => status.toUpperCase() == 'AVAILABLE' && hasFrame;

  factory CameraInfo.fromJson(Map<String, dynamic> j) => CameraInfo(
        status: j['status'] as String? ?? 'UNAVAILABLE',
        source: j['source'] as String? ?? 'UNAVAILABLE',
        hasFrame: j['has_frame'] as bool? ?? false,
        sourceName: j['source_name'] as String?,
        width: (j['width'] as num?)?.toInt(),
        height: (j['height'] as num?)?.toInt(),
        format: j['format'] as String?,
        frameId: (j['frame_id'] as num?)?.toInt(),
        timestamp: (j['timestamp'] as num?)?.toDouble(),
        error: j['error'] as String?,
      );
}

/// An image-space detection box from `/camera/overlay`.
class DetectionBox {
  const DetectionBox({
    required this.kind,
    required this.label,
    required this.confidence,
    required this.x,
    required this.y,
    required this.w,
    required this.h,
    this.severity,
  });

  final String kind;
  final String label;
  final double? confidence;
  final String? severity;
  final double x;
  final double y;
  final double w;
  final double h;

  factory DetectionBox.fromJson(Map<String, dynamic> j) {
    final bbox = (j['image_bbox'] as Map<String, dynamic>?) ?? const {};
    return DetectionBox(
      kind: j['kind'] as String? ?? '',
      label: j['label'] as String? ?? '',
      confidence: (j['confidence'] as num?)?.toDouble(),
      severity: j['severity'] as String?,
      x: (bbox['x'] as num?)?.toDouble() ?? 0,
      y: (bbox['y'] as num?)?.toDouble() ?? 0,
      w: (bbox['w'] as num?)?.toDouble() ?? 0,
      h: (bbox['h'] as num?)?.toDouble() ?? 0,
    );
  }
}

class CameraOverlay {
  const CameraOverlay({
    required this.detections,
    required this.count,
    required this.imageWidth,
    required this.imageHeight,
  });

  final List<DetectionBox> detections;
  final int count;
  final int? imageWidth;
  final int? imageHeight;

  factory CameraOverlay.fromJson(Map<String, dynamic> j) {
    final dets = (j['boxes'] as List<dynamic>? ?? const [])
        .map((e) => DetectionBox.fromJson(e as Map<String, dynamic>))
        .toList();
    final image = (j['image'] as Map<String, dynamic>?) ?? const {};
    return CameraOverlay(
      detections: dets,
      count: dets.length,
      imageWidth: (image['width'] as num?)?.toInt(),
      imageHeight: (image['height'] as num?)?.toInt(),
    );
  }
}

class ConnectivityInfo {
  const ConnectivityInfo({
    required this.wifi,
    required this.bluetooth,
    required this.interfaces,
    this.note,
  });

  final Map<String, dynamic> wifi;
  final Map<String, dynamic> bluetooth;
  final List<Map<String, dynamic>> interfaces;
  final String? note;

  factory ConnectivityInfo.fromJson(Map<String, dynamic> j) => ConnectivityInfo(
        wifi: (j['wifi'] as Map<String, dynamic>?) ?? const {},
        bluetooth: (j['bluetooth'] as Map<String, dynamic>?) ?? const {},
        interfaces: (j['interfaces'] as List<dynamic>? ?? const [])
            .map((e) => Map<String, dynamic>.from(e as Map))
            .toList(),
        note: j['note'] as String?,
      );
}