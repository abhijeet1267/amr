// A minimal smoke test for the AMR Controller shell.
//
// This does not boot the robot (the provider is created inert, so no network
// happens), and it does not assert on any hardcoded layout: it only checks
// that the app builds and the three navigation destinations are present. It is
// the "does it at least construct" gate that a real `flutter analyze` +
// `flutter test` CI would run, and it exists so the scaffold's generated
// counter test (which referenced a template `MyApp`) is gone.

import 'package:flutter_test/flutter_test.dart';

import 'package:amr_controller/main.dart';

void main() {
  testWidgets('the app shell builds with its three destinations',
      (WidgetTester tester) async {
    await tester.pumpWidget(const AmrControllerApp());
    await tester.pump();

    // Desktop-width default in the test harness is 800x600, which lands on the
    // NavigationRail shell. We only assert the nav labels exist, not the
    // widget class, so this stays true on a mobile-sized harness too.
    expect(find.text('Applications'), findsWidgets);
    expect(find.text('Teleop'), findsWidgets);
    expect(find.text('Connection'), findsWidgets);
  });
}