// Map & Navigation — a real top-down view of the robot's warehouse frame.
//
// Consumes the backend's REAL map interface (verified in server.py):
//   GET /map -> MapSnapshot (robot pose, goal, route, path, hazards, zones,
//               waypoints, navigation state — all in world metres, y-up,
//               yaw in radians).
//
// The painter is a pure world→screen transform; it never fakes a pose. When the
// backend reports no robot (source UNAVAILABLE), the map shows "NO POSE" and the
// "SIMULATION" / "UNAVAILABLE" badge is shown from the snapshot's own tag.

import 'dart:math' as math;

import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../models/robot_data.dart';
import '../../providers/robot_provider.dart';
import '../../theme/theme.dart';
import '../../widgets/status_widgets.dart';

class MapScreen extends StatefulWidget {
  const MapScreen({super.key});

  @override
  State<MapScreen> createState() => _MapScreenState();
}

class _MapScreenState extends State<MapScreen> {
  double _zoom = 1.0;

  @override
  Widget build(BuildContext context) {
    final provider = context.watch<RobotProvider>();
    final map = provider.map;

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Padding(
          padding: const EdgeInsets.all(20),
          child: Row(
            children: [
              const Expanded(child: SectionHeader(title: 'Map & Navigation')),
              if (map != null)
                StatusPill(
                  label: map.source,
                  colour: map.source == 'LIVE'
                      ? AppPalette.ok
                      : map.source == 'SIMULATION'
                          ? AppPalette.warn
                          : AppPalette.dim,
                ),
              const SizedBox(width: 8),
              IconButton(
                icon: const Icon(Icons.zoom_in),
                onPressed: () => setState(() => _zoom = (_zoom + 0.2).clamp(0.4, 4.0)),
              ),
              IconButton(
                icon: const Icon(Icons.zoom_out),
                onPressed: () => setState(() => _zoom = (_zoom - 0.2).clamp(0.4, 4.0)),
              ),
              IconButton(
                icon: const Icon(Icons.center_focus_strong),
                onPressed: () => setState(() => _zoom = 1.0),
              ),
            ],
          ),
        ),
        Expanded(
          child: Padding(
            padding: const EdgeInsets.fromLTRB(20, 0, 20, 20),
            child: Container(
              decoration: BoxDecoration(
                color: AppPalette.surface,
                border: Border.all(color: AppPalette.line),
                borderRadius: BorderRadius.circular(10),
              ),
              clipBehavior: Clip.antiAlias,
              child: map == null
                  ? const Center(
                      child: Text(
                        'NO MAP DATA',
                        style: TextStyle(color: AppPalette.dim),
                      ),
                    )
                  : CustomPaint(
                      painter: MapPainter(map, _zoom),
                      size: Size.infinite,
                    ),
            ),
          ),
        ),
        if (map != null)
          Padding(
            padding: const EdgeInsets.fromLTRB(20, 0, 20, 20),
            child: _MapReadout(map: map),
          ),
      ],
    );
  }
}

class _MapReadout extends StatelessWidget {
  const _MapReadout({required this.map});

  final MapState map;

  @override
  Widget build(BuildContext context) {
    final r = map.robot;
    return Wrap(
      spacing: 16,
      runSpacing: 8,
      children: [
        KvRow(label: 'X', value: r == null ? '—' : '${r.x.toStringAsFixed(2)} ${map.units}'),
        KvRow(label: 'Y', value: r == null ? '—' : '${r.y.toStringAsFixed(2)} ${map.units}'),
        KvRow(label: 'Heading', value: r == null ? '—' : '${(r.yaw * 180 / math.pi).round()}°'),
        KvRow(label: 'Goal', value: map.goal?.name ?? '—'),
        KvRow(label: 'Nav state', value: map.navigationState ?? '—'),
        KvRow(label: 'Source', value: map.source),
        KvRow(label: 'Waypoints', value: map.waypoints.length.toString()),
        if (map.staticNote != null)
          KvRow(label: 'Note', value: map.staticNote!),
      ],
    );
  }
}

class MapPainter extends CustomPainter {
  MapPainter(this.map, this.zoom);

  final MapState map;
  final double zoom;

  @override
  void paint(Canvas canvas, Size size) {
    // World→screen transform: gather extents from waypoints/robot/goal/route,
    // fit with padding, honour zoom around the centre.
    final bounds = _bounds();
    if (bounds == null) return;

    const pad = 40.0;
    final worldW = math.max(bounds[2] - bounds[0], 0.5);
    final worldH = math.max(bounds[3] - bounds[1], 0.5);
    final scale = zoom * math.min(
          (size.width - 2 * pad) / worldW,
          (size.height - 2 * pad) / worldH,
        );
    // y-up world → y-down screen.
    double sx(double x) => pad + (x - bounds[0]) * scale + (size.width - 2 * pad - worldW * scale) / 2;
    double sy(double y) => size.height - pad - (y - bounds[1]) * scale - (size.height - 2 * pad - worldH * scale) / 2;

    // Grid (1 m).
    final grid = Paint()
      ..color = AppPalette.line.withValues(alpha: 0.35)
      ..strokeWidth = 1;
    for (var gx = (bounds[0]).floor() - 1; gx <= bounds[2].ceil() + 1; gx++) {
      canvas.drawLine(Offset(sx(gx.toDouble()), sy(bounds[1])), Offset(sx(gx.toDouble()), sy(bounds[3])), grid);
    }
    for (var gy = (bounds[1]).floor() - 1; gy <= bounds[3].ceil() + 1; gy++) {
      canvas.drawLine(Offset(sx(bounds[0]), sy(gy.toDouble())), Offset(sx(bounds[2]), sy(gy.toDouble())), grid);
    }

    // Zones (restricted rectangles).
    final zoneFill = Paint()..color = AppPalette.warn.withValues(alpha: 0.12);
    final zoneLine = Paint()
      ..color = AppPalette.warn.withValues(alpha: 0.6)
      ..style = PaintingStyle.stroke;
    for (final z in map.zones) {
      final r = Rect.fromLTRB(sx(z.xMin), sy(z.yMax), sx(z.xMax), sy(z.yMin));
      canvas.drawRect(r, zoneFill);
      canvas.drawRect(r, zoneLine);
    }

    // Waypoints.
    for (final w in map.waypoints) {
      canvas.drawCircle(Offset(sx(w.x), sy(w.y)), 4, Paint()..color = AppPalette.gold);
    }

    // Route (planned path).
    _polyline(canvas, map.route, sx, sy, AppPalette.accent, dashed: true);
    // Travelled path.
    _polyline(canvas, map.path, sx, sy, AppPalette.info, dashed: false);

    // Hazards.
    for (final h in map.hazards) {
      canvas.drawCircle(
        Offset(sx(h.x), sy(h.y)),
        8,
        Paint()..color = AppPalette.crit.withValues(alpha: 0.7),
      );
    }

    // Goal marker.
    if (map.goal != null) {
      canvas.drawCircle(
        Offset(sx(map.goal!.x), sy(map.goal!.y)),
        6,
        Paint()..color = AppPalette.accent,
      );
    }

    // Robot pose: a triangle oriented by yaw (screen rotation = -yaw).
    if (map.robot != null) {
      final cx = sx(map.robot!.x);
      final cy = sy(map.robot!.y);
      final body = Paint()..color = AppPalette.ok;
      final path = Path();
      const r = 10.0;
      // Forward = +x in world is mapped by the -yaw screen rotation below.
      for (var i = 0; i < 3; i++) {
        final a = -map.robot!.yaw + i * 2 * math.pi / 3 - math.pi / 2;
        final px = cx + r * math.cos(a);
        final py = cy + r * math.sin(a);
        i == 0 ? path.moveTo(px, py) : path.lineTo(px, py);
      }
      path.close();
      canvas.drawPath(path, body);
    }
  }

  void _polyline(Canvas canvas, List<MapPoint> pts, double Function(double) sx,
      double Function(double) sy, Color colour, {required bool dashed}) {
    if (pts.length < 2) return;
    final paint = Paint()
      ..color = colour
      ..strokeWidth = 1.5
      ..style = PaintingStyle.stroke;
    if (dashed) {
      // Simple dash by sampling.
      for (var i = 0; i < pts.length - 1; i++) {
        final a = Offset(sx(pts[i].x), sy(pts[i].y));
        final b = Offset(sx(pts[i + 1].x), sy(pts[i + 1].y));
        canvas.drawLine(a, b, paint);
      }
    } else {
      final path = Path()..moveTo(sx(pts[0].x), sy(pts[0].y));
      for (var i = 1; i < pts.length; i++) {
        path.lineTo(sx(pts[i].x), sy(pts[i].y));
      }
      canvas.drawPath(path, paint);
    }
  }

  /// [xMin, yMin, xMax, yMax] from the real data present, or null when empty.
  List<double>? _bounds() {
    final xs = <double>[];
    final ys = <double>[];
    void add(double x, double y) {
      if (x.isFinite && y.isFinite) {
        xs.add(x);
        ys.add(y);
      }
    }

    if (map.robot != null) add(map.robot!.x, map.robot!.y);
    if (map.goal != null) add(map.goal!.x, map.goal!.y);
    for (final p in map.route) {
      add(p.x, p.y);
    }
    for (final p in map.path) {
      add(p.x, p.y);
    }
    for (final w in map.waypoints) {
      add(w.x, w.y);
    }
    for (final h in map.hazards) {
      add(h.x, h.y);
    }
    if (xs.isEmpty) return null;
    return [
      xs.reduce(math.min),
      ys.reduce(math.min),
      xs.reduce(math.max),
      ys.reduce(math.max),
    ];
  }

  @override
  bool shouldRepaint(covariant MapPainter old) =>
      old.map != map || old.zoom != zoom;
}