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