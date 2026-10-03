// Model/parser unit tests — the null-honesty guarantees that the rest of the
// suite leans on. "No sensor" must stay null, never become 0.

import 'package:flutter_test/flutter_test.dart';

import 'package:amr_controller/models/app_state.dart';

void main() {
  group('TelemetryState parsing', () {
    test('a fully-populated snapshot maps field-for-field', () {
      final t = TelemetryState.fromJson(<String, dynamic>{
        'system': <String, dynamic>{
          'robot_id': 'amr-robot',
          'connected': true,
          'mode': 'MANUAL',
          'simulated': true,
          'last_error': null,
        },
        'battery': <String, dynamic>{'percentage': 87.5, 'voltage': 12.2},
        'sensors': <String, dynamic>{
          'front_cm': 42,
          'left_cm': 40,
          'right_cm': 41,
          'rear_cm': 43,
        },
        'velocity': <String, dynamic>{'linear': 0.5},
        'safety': <String, dynamic>{'action': 'PROCEED', 'emergency_stop': false},
      });

      expect(t.robotId, 'amr-robot');
      expect(t.connected, isTrue);
      expect(t.mode, 'MANUAL');
      expect(t.batteryPercentage, 87.5);
      expect(t.batteryVoltage, 12.2);
      expect(t.frontCm, 42);
      expect(t.speedMps, 0.5);
      expect(t.emergencyStop, isFalse);
    });

    test('a missing battery sensor stays null, never 0', () {
      final t = TelemetryState.fromJson(<String, dynamic>{
        'system': <String, dynamic>{},
        'battery': <String, dynamic>{'percentage': null, 'voltage': null},
        'sensors': <String, dynamic>{},
        'velocity': <String, dynamic>{},
        'safety': <String, dynamic>{},
      });

      expect(t.batteryPercentage, isNull);
      expect(t.batteryVoltage, isNull);
      expect(t.frontCm, isNull);
      expect(t.speedMps, isNull);
    });

    test('non-numeric battery values degrade to null, not a crash', () {
      final t = TelemetryState.fromJson(<String, dynamic>{
        'system': <String, dynamic>{},
        'battery': <String, dynamic>{'percentage': 'not-a-number'},
        'sensors': <String, dynamic>{'front_cm': 'nan'},
        'velocity': <String, dynamic>{'linear': 'inf'},
        'safety': <String, dynamic>{},
      });

      expect(t.batteryPercentage, isNull);
      expect(t.frontCm, isNull);
      expect(t.speedMps, isNull);
    });
  });

  group('AppState parsing', () {
    test('a registry entry maps all fields and defaults safe', () {
      final a = AppState.fromJson(<String, dynamic>{
        'id': 'command_center',
        'name': 'AMR Command Center',
        'description': '  wraps   whitespace  ',
        'category': 'monitoring',
        'platforms': <String>['web', 'android'],
        'url': '/command-center',
        'read_only': true,
        'requires_robot': true,
        'status': 'MOCK',
        'reason': 'mock-robot',
      });

      expect(a.id, 'command_center');
      expect(a.name, 'AMR Command Center');
      // The model passes description through verbatim (the robot server does
      // the whitespace collapse); assert the pass-through, not a rewrite.
      expect(a.description, '  wraps   whitespace  ');
      expect(a.platforms, ['web', 'android']);
      expect(a.hasInterface, isTrue);
      expect(a.readOnly, isTrue);
    });

    test('an entry with no url is not an interface', () {
      final a = AppState.fromJson(<String, dynamic>{'id': 'api_reference', 'url': null});
      expect(a.hasInterface, isFalse);
    });
  });
}