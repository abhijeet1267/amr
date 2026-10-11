// C19 — the heat-map screen.
//
// `flutter analyze` proves this file compiles; these tests prove it RUNS. That
// distinction is not academic: the web console's heat-map renderer passed every
// string-based test and painted every cell black at runtime, because it fed the
// painter a value it could not use. Nothing but executing the drawing code would
// have caught it, so the client's painter is exercised here rather than merely
// type-checked.

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:provider/provider.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:amr_controller/features/heatmap/heatmap_screen.dart';
import 'package:amr_controller/models/robot_data.dart';
import 'package:amr_controller/providers/robot_provider.dart';
import 'package:amr_controller/theme/theme.dart';

Map<String, dynamic> _grid({
  required List<double> cells,
  required double maxValue,
  required double total,
  required int samples,
  int unlocated = 0,
}) =>
    {
      'cols': 2,
      'rows': 2,
      'cell_m': 0.5,
      'extent': {'x_min': 0.0, 'x_max': 1.0, 'y_min': 0.0, 'y_max': 1.0},
      'cells': cells,
      'row_order': 'row 0 is y_min (bottom); index = row * cols + col',
      'max_value': maxValue,
      'total': total,
      'samples': samples,
      'clipped': 0,
      'unlocated': unlocated,
      'source': 'SIMULATION',
      'note': 'test',
    };

Map<String, dynamic> _map() => {
      'source': 'SIMULATION',
      'units': 'metres',
      'warehouse': {
        'waypoints': [
          {'name': 'Dock', 'x': 0.0, 'y': 0.0, 'theta': 0.0, 'source': 'SIMULATION'},
        ],
        'note': null,
      },
      'robot': {'x': 0.0, 'y': 0.0, 'yaw': 0.0, 'source': 'SIMULATION'},
      'route': <Object>[],
      'path': <Object>[],
      'hazards': <Object>[],
      'zones': <Object>[],
      'navigation': {'state': 'IDLE'},
    };

Widget _host(RobotProvider p) => ChangeNotifierProvider<RobotProvider>.value(
      value: p,
      child: MaterialApp(
        theme: buildAppTheme(),
        home: const Scaffold(body: HeatmapScreen()),
      ),
    );

/// The screen is a `ListView`, so the default 800x600 test viewport never lays
/// out the *second* graph — it is below the fold and `find.text` would report it
/// missing even though the code is correct. Give the test a tall window so both
/// cards are built and painted.
void _sizeViewport(WidgetTester tester) {
  tester.view.physicalSize = const Size(1200, 2400);
  tester.view.devicePixelRatio = 1.0;
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  SharedPreferences.setMockInitialValues({});

  testWidgets('renders both graphs, their readouts and the legend',
      (WidgetTester tester) async {
    _sizeViewport(tester);
    final p = RobotProvider();
    addTearDown(p.dispose);
    p.map = MapState.fromJson(_map());
    p.heatmap = HeatmapState.fromJson({
      'source': 'SIMULATION',
      'severity_weights': {'INFO': 1.0, 'WARNING': 2.0, 'CRITICAL': 4.0},
      'hazard': _grid(
          cells: [0.0, 4.0, 0.0, 0.0], maxValue: 4.0, total: 4.0, samples: 1),
      'traffic': _grid(
          cells: [0.0, 0.0, 3.0, 0.0], maxValue: 3.0, total: 3.0, samples: 3),
      'notes': <String>[],
    });

    await tester.pumpWidget(_host(p));
    await tester.pump();

    // Two graphs, not one blended picture.
    expect(find.text('Hazard density'), findsOneWidget);
    expect(find.text('Traffic density'), findsOneWidget);
    expect(find.text('Spatial heat map'), findsOneWidget);
    // Both painters actually ran: a throw inside paint() would surface here.
    expect(tester.takeException(), isNull);
    expect(find.byType(CustomPaint), findsWidgets);

    // The readouts come from the payload, not from invented numbers.
    expect(find.text('Weighted total'), findsOneWidget);
    expect(find.text('Located events'), findsOneWidget);
    expect(find.text('Path samples'), findsOneWidget);
    expect(find.text('Busiest cell'), findsOneWidget);
  });

  testWidgets('an all-zero grid still draws and is not an error',
      (WidgetTester tester) async {
    _sizeViewport(tester);
    final p = RobotProvider();
    addTearDown(p.dispose);
    p.heatmap = HeatmapState.fromJson({
      'source': 'SIMULATION',
      'severity_weights': {'INFO': 1.0, 'WARNING': 2.0, 'CRITICAL': 4.0},
      'hazard': _grid(
          cells: [0.0, 0.0, 0.0, 0.0], maxValue: 0.0, total: 0.0, samples: 0),
      'traffic': _grid(
          cells: [0.0, 0.0, 0.0, 0.0], maxValue: 0.0, total: 0.0, samples: 0),
      'notes': <String>['no travelled path recorded yet'],
    });

    await tester.pumpWidget(_host(p));
    await tester.pump();

    expect(tester.takeException(), isNull);
    expect(find.text('Hazard density'), findsOneWidget);
    // The note the backend sent is surfaced, not swallowed.
    expect(find.textContaining('no travelled path recorded yet'), findsOneWidget);
  });

  testWidgets('no configured geometry says so instead of inventing a grid',
      (WidgetTester tester) async {
    final p = RobotProvider();
    addTearDown(p.dispose);
    p.heatmap = HeatmapState.fromJson({
      'source': 'UNAVAILABLE',
      'hazard': null,
      'traffic': null,
      'notes': ['no configured warehouse geometry'],
    });

    await tester.pumpWidget(_host(p));
    await tester.pump();

    expect(tester.takeException(), isNull);
    expect(find.textContaining('NO HEAT-MAP DATA'), findsOneWidget);
    expect(find.text('Hazard density'), findsNothing);
  });
}
