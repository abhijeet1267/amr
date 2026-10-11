// Tests for the V2 data models (map/camera/connectivity) and the simulation
// mode, which must never issue a command.

import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:amr_controller/models/robot_data.dart';
import 'package:amr_controller/providers/robot_provider.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  SharedPreferences.setMockInitialValues({});
  group('MapState parsing', () {
    test('parses the real /map payload shape', () {
      final m = MapState.fromJson({
        'schema_version': '1.0',
        'source': 'SIMULATION',
        'units': 'metres',
        'warehouse': {
          'waypoints': [
            {'name': 'Dock', 'x': 0.5, 'y': 0.5, 'theta': 0.0, 'source': 'SIMULATION'},
          ],
          'note': 'not modelled',
        },
        'robot': {'x': 4.5, 'y': 3.0, 'yaw': 0.5, 'source': 'SIMULATION'},
        'goal': null,
        'route': [
          {'x': 0.0, 'y': 0.0},
          {'x': 1.0, 'y': 1.0},
        ],
        'path': <Map<String, dynamic>>[],
        'hazards': [
          {'kind': 'FIRE', 'severity': 'CRITICAL', 'confidence': 0.9, 'x': 2.0, 'y': 2.0, 'source': 'SIMULATION'},
        ],
        'zones': [
          {'name': 'restricted', 'x_min': 1.0, 'x_max': 2.0, 'y_min': 1.0, 'y_max': 2.0},
        ],
        'navigation': {'state': 'IDLE'},
      });

      expect(m.source, 'SIMULATION');
      expect(m.units, 'metres');
      expect(m.waypoints.single.name, 'Dock');
      expect(m.robot!.x, 4.5);
      expect(m.route, hasLength(2));
      expect(m.hazards.single.kind, 'FIRE');
      expect(m.zones.single.name, 'restricted');
      expect(m.navigationState, 'IDLE');
      expect(m.staticNote, 'not modelled');
      expect(m.isLive, isFalse);
    });
  });

  group('CameraOverlay parsing', () {
    test('parses image-space boxes from /camera/overlay', () {
      final o = CameraOverlay.fromJson({
        'image': {'width': 1280, 'height': 720},
        'boxes': [
          {
            'kind': 'PERSON',
            'label': 'person',
            'confidence': 0.87,
            'image_bbox': {'x': 400.0, 'y': 200.0, 'w': 120.0, 'h': 220.0},
          },
        ],
        'box_count': 1,
      });

      expect(o.count, 1);
      expect(o.imageWidth, 1280);
      expect(o.imageHeight, 720);
      expect(o.detections.single.label, 'person');
      expect(o.detections.single.x, 400.0);
      expect(o.detections.single.w, 120.0);
    });
  });

  group('HeatmapState parsing', () {
    test('parses the real /heatmap payload shape', () {
      final h = HeatmapState.fromJson({
        'schema_version': '1.0',
        'source': 'SIMULATION',
        'units': 'metres',
        'severity_weights': {'INFO': 1.0, 'WARNING': 2.0, 'CRITICAL': 4.0},
        'hazard': {
          'cols': 2,
          'rows': 2,
          'cell_m': 0.5,
          'extent': {'x_min': 0.0, 'x_max': 1.0, 'y_min': 0.0, 'y_max': 1.0},
          'cells': [0.0, 4.0, 0.0, 0.0],
          'max_value': 4.0,
          'total': 4.0,
          'samples': 1,
          'clipped': 0,
          'unlocated': 2,
          'source': 'SIMULATION',
          'note': 'weighted',
        },
        'traffic': null,
        'notes': ['2 recorded hazard event(s) carried no world location'],
      });

      expect(h.source, 'SIMULATION');
      expect(h.hasAny, isTrue);
      expect(h.severityWeights['CRITICAL'], 4.0);
      expect(h.traffic, isNull);
      expect(h.notes, hasLength(1));

      final g = h.hazard!;
      expect(g.cols, 2);
      expect(g.rows, 2);
      expect(g.maxValue, 4.0);
      expect(g.unlocated, 2);
      // Row-major with row 0 at y_min (the BOTTOM row): index 1 is column 1 of
      // that bottom row. Getting this backwards mirrors the picture silently.
      expect(g.at(1, 0), 4.0);
      expect(g.at(0, 0), 0.0);
      expect(g.at(1, 1), 0.0);
      // Out-of-range reads are zero, never an exception.
      expect(g.at(-1, 0), 0.0);
      expect(g.at(9, 9), 0.0);
    });

    test('no configured geometry means no grid, not an invented one', () {
      final h = HeatmapState.fromJson({
        'source': 'UNAVAILABLE',
        'hazard': null,
        'traffic': null,
        'notes': ['no configured warehouse geometry'],
      });
      expect(h.hasAny, isFalse);
      expect(h.hazard, isNull);
      expect(h.traffic, isNull);
      expect(h.severityWeights, isEmpty);
      expect(h.notes, hasLength(1));
    });
  });

  group('Simulation mode', () {
    test('entering simulation marks connected with simulated telemetry', () async {
      final p = RobotProvider();
      addTearDown(p.dispose);
      await p.setSimulation(true);

      expect(p.simulation, isTrue);
      expect(p.isConnected, isTrue);
      expect(p.telemetry, isNotNull);
      expect(p.telemetry!.simulated, isTrue);
      expect(p.map, isNotNull);
      expect(p.map!.source, 'SIMULATION');
    });

    test('simulation never issues a command', () async {
      final p = RobotProvider();
      addTearDown(p.dispose);
      await p.setSimulation(true);

      final ok = await p.command('forward', speed: 50);
      expect(ok, isFalse);
      expect(p.lastCommandError, contains('simulation'));
    });
  });
}