// A minimal smoke test for the AMR Controller shell.
//
// Does not boot the robot (the provider is inert). Asserts the shell constructs
// and the core destinations are present, without pinning the whole nav list.
//
// The shell is no longer the first screen: a fresh install opens the setup
// wizard (see `setup_wizard_test.dart`). This test therefore marks setup as
// already complete so it exercises the console, which is its subject.

import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:amr_controller/main.dart';

void main() {
  testWidgets('the app shell builds with its navigation destinations',
      (WidgetTester tester) async {
    SharedPreferences.setMockInitialValues(
        <String, Object>{'amr.setup_complete': true});

    await tester.pumpWidget(const AmrControllerApp());
    await tester.pump();
    await tester.pump();

    // The console shell has many destinations in a lazy, scrollable rail; assert
    // the core destinations render (dashboard content may repeat some labels).
    expect(find.text('Dashboard'), findsWidgets);
    expect(find.text('Camera'), findsWidgets);
    expect(find.text('Map'), findsWidgets);
    expect(find.text('Teleop'), findsWidgets);
    expect(find.text('Missions'), findsWidgets);
  });
}
