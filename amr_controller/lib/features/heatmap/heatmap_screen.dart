// Spatial heat map (C19) — two densities over one shared extent.
//
// Consumes the backend's real heat-map interface (verified in server.py):
//   GET /heatmap -> { hazard: HeatGrid, traffic: HeatGrid, severity_weights }
//
// Both grids are binned in **Python**, server-side, over the *configured*
// warehouse extent, so this screen never re-derives a cell index and the two
// graphs are directly comparable. Nothing here is invented: an empty grid says
// "no samples recorded" rather than shading a plausible-looking zero.
//
// The drawing surface is the app's white panel, matching the Map screen, so the
// client stays one light control-room surface throughout.

import 'dart:math' as math;

import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../models/robot_data.dart';
import '../../providers/robot_provider.dart';
import '../../theme/theme.dart';
import '../../widgets/status_widgets.dart';

/// Interpolate a colour ramp at `t` in `[0, 1]`.
Color rampColour(List<Color> stops, double t) {
  if (t <= 0) return stops.first;
  if (t >= 1) return stops.last;
  final seg = (stops.length - 1) * t;
  final i = seg.floor().clamp(0, stops.length - 2);
  return Color.lerp(stops[i], stops[i + 1], seg - i) ?? stops[i];
}

class HeatmapScreen extends StatelessWidget {
  const HeatmapScreen({super.key});

  @override
  Widget build(BuildContext context) {
    final provider = context.watch<RobotProvider>();
    final hm = provider.heatmap;

    return ListView(
      padding: const EdgeInsets.all(20),
      children: [
        Row(
          children: [
            const Expanded(child: SectionHeader(title: 'Spatial heat map')),
            if (hm != null)
              StatusPill(
                label: hm.source,
                colour: hm.source == 'LIVE'
                    ? AppPalette.ok
                    : hm.source == 'SIMULATION'
                        ? AppPalette.warn
                        : AppPalette.dim,
              ),
          ],
        ),
        const Text(
          'Two density grids over one shared extent, binned on the robot from '
          'the same map snapshot the Map screen draws — so the two graphs are '
          'directly comparable.',
          style: TextStyle(fontSize: 12, color: AppPalette.muted, height: 1.5),
        ),
        const SizedBox(height: 16),
        if (hm == null || !hm.hasAny)
          const _NoGrid()
        else ...[
          _HeatCard(
            title: 'Hazard density',
            grid: hm.hazard,
            ramp: const [AppPalette.line, AppPalette.warn, AppPalette.crit],
            legendNote: 'recorded hazard events, weighted by severity '
                '(a CRITICAL cell counts 4x a WARNING)',
            map: provider.map,
            readout: (g) => [
              KvRow(label: 'Weighted total', value: g.total.toStringAsFixed(0)),
              KvRow(label: 'Located events', value: g.samples.toString()),
              KvRow(label: 'Unplaced events', value: g.unlocated.toString()),
            ],
          ),
          const SizedBox(height: 16),
          _HeatCard(
            title: 'Traffic density',
            grid: hm.traffic,
            ramp: const [AppPalette.line, AppPalette.accent],
            legendNote: 'one sample per recorded path point, so a cell is time '
                'spent there rather than distance travelled',
            map: provider.map,
            readout: (g) => [
              KvRow(label: 'Path samples', value: g.samples.toString()),
              KvRow(label: 'Busiest cell', value: g.maxValue.toStringAsFixed(0)),
              KvRow(label: 'Cells visited',
                  value: g.cells.where((v) => v > 0).length.toString()),
            ],
          ),
          if (hm.notes.isNotEmpty)
            Padding(
              padding: const EdgeInsets.only(top: 12),
              child: Text(
                hm.notes.join(' · '),
                style: const TextStyle(fontSize: 11, color: AppPalette.dim),
              ),
            ),
        ],
      ],
    );
  }
}

class _NoGrid extends StatelessWidget {
  const _NoGrid();

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(24),
      decoration: BoxDecoration(
        color: AppPalette.surface,
        border: Border.all(color: AppPalette.line),
        borderRadius: BorderRadius.circular(10),
      ),
      child: const Text(
        'NO HEAT-MAP DATA — the robot has no configured warehouse geometry to '
        'bin over, so no grid is drawn rather than an invented one.',
        style: TextStyle(color: AppPalette.dim, fontSize: 12, height: 1.5),
      ),
    );
  }
}

class _HeatCard extends StatelessWidget {
  const _HeatCard({
    required this.title,
    required this.grid,
    required this.ramp,
    required this.legendNote,
    required this.map,
    required this.readout,
  });

  final String title;
  final HeatGrid? grid;
  final List<Color> ramp;
  final String legendNote;
  final MapState? map;
  final List<KvRow> Function(HeatGrid grid) readout;

  @override
  Widget build(BuildContext context) {
    final g = grid;
    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: AppPalette.surface,
        border: Border.all(color: AppPalette.line),
        borderRadius: BorderRadius.circular(10),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            title,
            style: const TextStyle(
              fontSize: 13,
              fontWeight: FontWeight.w600,
              color: AppPalette.text,
            ),
          ),
          const SizedBox(height: 10),
          if (g == null)
            const SizedBox(
              height: 180,
              child: Center(
                child: Text('UNAVAILABLE',
                    style: TextStyle(color: AppPalette.dim, fontSize: 12)),
              ),
            )
          else ...[
            AspectRatio(
              aspectRatio: 10 / 7,
              child: Container(
                decoration: BoxDecoration(
                  color: AppPalette.background,
                  border: Border.all(color: AppPalette.line),
                  borderRadius: BorderRadius.circular(8),
                ),
                clipBehavior: Clip.antiAlias,
                child: CustomPaint(
                  painter: HeatGridPainter(grid: g, ramp: ramp, map: map),
                  size: Size.infinite,
                ),
              ),
            ),
            const SizedBox(height: 10),
            _Legend(grid: g, ramp: ramp),
            const SizedBox(height: 4),
            Text(
              legendNote,
              style: const TextStyle(
                  fontSize: 11, color: AppPalette.dim, height: 1.4),
            ),
            const SizedBox(height: 10),
            Wrap(
              spacing: 16,
              runSpacing: 8,
              children: readout(g),
            ),
          ],
        ],
      ),
    );
  }
}

class _Legend extends StatelessWidget {
  const _Legend({required this.grid, required this.ramp});

  final HeatGrid grid;
  final List<Color> ramp;

  @override
  Widget build(BuildContext context) {
    return Row(
      children: [
        const Text('0',
            style: TextStyle(fontSize: 11, color: AppPalette.dim)),
        const SizedBox(width: 6),
        for (var i = 0; i <= 4; i++)
          Container(
            width: 28,
            height: 10,
            margin: const EdgeInsets.only(right: 3),
            decoration: BoxDecoration(
              color: rampColour(ramp, i / 4),
              borderRadius: BorderRadius.circular(2),
              border: Border.all(color: AppPalette.line),
            ),
          ),
        const SizedBox(width: 3),
        Text(
          grid.maxValue.toStringAsFixed(0),
          style: const TextStyle(fontSize: 11, color: AppPalette.dim),
        ),
      ],
    );
  }
}

/// Draws one binned grid: the cells, the extent frame, and the warehouse
/// context (waypoints and the robot) so the densities are readable in place.
class HeatGridPainter extends CustomPainter {
  HeatGridPainter({required this.grid, required this.ramp, required this.map});

  final HeatGrid grid;
  final List<Color> ramp;
  final MapState? map;

  @override
  void paint(Canvas canvas, Size size) {
    if (grid.cols <= 0 || grid.rows <= 0) return;

    const pad = 16.0;
    final spanX = math.max(grid.xMax - grid.xMin, 0.001);
    final spanY = math.max(grid.yMax - grid.yMin, 0.001);
    final scale = math.min(
      (size.width - 2 * pad) / spanX,
      (size.height - 2 * pad) / spanY,
    );
    final offX = (grid.xMin + grid.xMax) / 2;
    final offY = (grid.yMin + grid.yMax) / 2;

    // One world -> screen conversion. World y is up, canvas y is down, so the
    // sign flips exactly once, here — the same rule the Map screen applies.
    double sx(double x) => size.width / 2 + (x - offX) * scale;
    double sy(double y) => size.height / 2 - (y - offY) * scale;

    final peak = grid.maxValue;

    // Cells. Row 0 is yMin (the bottom row): the payload says so, and flipping
    // it would draw a plausible, mirrored picture.
    final fill = Paint();
    var drawn = 0;
    for (var row = 0; row < grid.rows; row++) {
      for (var col = 0; col < grid.cols; col++) {
        final v = grid.at(col, row);
        if (v <= 0) continue;
        drawn++;
        final t = peak > 0 ? (v / peak).clamp(0.0, 1.0) : 0.0;
        fill.color = rampColour(ramp, t);
        final x0 = grid.xMin + col * grid.cellM;
        final y0 = grid.yMin + row * grid.cellM;
        canvas.drawRect(
          Rect.fromLTRB(sx(x0), sy(y0 + grid.cellM), sx(x0 + grid.cellM), sy(y0)),
          fill,
        );
      }
    }

    // Extent frame — explicitly a data frame, never a surveyed wall.
    canvas.drawRect(
      Rect.fromLTRB(
          sx(grid.xMin), sy(grid.yMax), sx(grid.xMax), sy(grid.yMin)),
      Paint()
        ..color = AppPalette.line
        ..style = PaintingStyle.stroke
        ..strokeWidth = 1,
    );

    // Waypoints, so a cell can be read against a real place.
    final wp = Paint()..color = AppPalette.muted;
    for (final w in (map?.waypoints ?? const <MapWaypoint>[])) {
      canvas.drawCircle(Offset(sx(w.x), sy(w.y)), 3, wp);
    }

    // The robot, so "hot near the robot" is visible at a glance.
    final r = map?.robot;
    if (r != null) {
      canvas.drawCircle(
          Offset(sx(r.x), sy(r.y)), 6, Paint()..color = AppPalette.brand);
    }

    if (drawn == 0) {
      final tp = TextPainter(
        text: const TextSpan(
          text: 'no samples recorded',
          style: TextStyle(fontSize: 12, color: AppPalette.dim),
        ),
        textDirection: TextDirection.ltr,
      )..layout();
      tp.paint(
        canvas,
        Offset((size.width - tp.width) / 2, (size.height - tp.height) / 2),
      );
    }
  }

  @override
  bool shouldRepaint(covariant HeatGridPainter old) =>
      old.grid != grid || old.map != map || old.ramp != ramp;
}
