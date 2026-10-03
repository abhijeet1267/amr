// AMR Controller — app entry point.
//
// Owns the MaterialApp, the shared theme, the ChangeNotifierProvider that every
// screen reads, and the small navigation shell that swaps between the desktop
// split view and the mobile bottom-nav layout. Nothing here reaches the robot:
// the provider is constructed inert and only starts polling once an operator
// has entered a host, so launching the app against a dead robot is a clean
// "Disconnected" state rather than a background error storm.
library;

import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import 'providers/robot_provider.dart';
import 'screens/applications_hub_screen.dart';
import 'screens/connection_screen.dart';
import 'screens/teleop_screen.dart';
import 'theme/theme.dart';

void main() {
  WidgetsFlutterBinding.ensureInitialized();
  runApp(const AmrControllerApp());
}

class AmrControllerApp extends StatelessWidget {
  const AmrControllerApp({super.key, this.provider});

  /// Optional injected [RobotProvider]. Defaults to a fresh production provider,
  /// so `main()` runs unchanged; tests and harnesses inject one wired to a mock
  /// robot without forking the app's own networking path.
  final RobotProvider? provider;

  @override
  Widget build(BuildContext context) {
    return ChangeNotifierProvider(
      // The provider owns the API client and all shared state. It is created
      // once here and lives for the app's lifetime; the connection persists
      // across navigation, which is what lets the E-STOP stay reachable from
      // every screen.
      create: (_) => (provider ?? RobotProvider())..loadSavedConnection(),
      child: MaterialApp(
        title: 'AMR Controller',
        debugShowCheckedModeBanner: false,
        theme: buildAppTheme(),
        home: const RootShell(),
      ),
    );
  }
}

/// The navigation root. Desktop gets a split-view sidebar (Rail on the left,
/// content beside it); mobile gets a skimmable NavigationBar at the bottom.
///
/// Both shells expose the same three destinations, and the E-STOP affordance
/// is hoisted into the shell so it is reachable from *any* screen, exactly as
/// the spec requires.
class RootShell extends StatefulWidget {
  const RootShell({super.key});

  @override
  State<RootShell> createState() => _RootShellState();
}

class _RootShellState extends State<RootShell> {
  int _index = 0;

  static const _destinations = [
    NavigationDestination(
      icon: Icon(Icons.hub_outlined),
      selectedIcon: Icon(Icons.hub),
      label: 'Applications',
    ),
    NavigationDestination(
      icon: Icon(Icons.gamepad_outlined),
      selectedIcon: Icon(Icons.gamepad),
      label: 'Teleop',
    ),
    NavigationDestination(
      icon: Icon(Icons.settings_input_component_outlined),
      selectedIcon: Icon(Icons.settings_input_component),
      label: 'Connection',
    ),
  ];

  @override
  Widget build(BuildContext context) {
    final isWide = MediaQuery.sizeOf(context).width >= 800;
    final content = <Widget>[
      const ApplicationsHubScreen(),
      const TeleopScreen(),
      const ConnectionScreen(),
    ][_index];

    if (isWide) {
      return Scaffold(
        body: Row(
          children: [
            NavigationRail(
              selectedIndex: _index,
              onDestinationSelected: (i) => setState(() => _index = i),
              labelType: NavigationRailLabelType.all,
              leading: const _RailHeader(),
              destinations: const [
                NavigationRailDestination(
                  icon: Icon(Icons.hub_outlined),
                  selectedIcon: Icon(Icons.hub),
                  label: Text('Applications'),
                ),
                NavigationRailDestination(
                  icon: Icon(Icons.gamepad_outlined),
                  selectedIcon: Icon(Icons.gamepad),
                  label: Text('Teleop'),
                ),
                NavigationRailDestination(
                  icon: Icon(Icons.settings_input_component_outlined),
                  selectedIcon: Icon(Icons.settings_input_component),
                  label: Text('Connection'),
                ),
              ],
            ),
            const VerticalDivider(width: 1),
            Expanded(child: content),
          ],
        ),
      );
    }

    return Scaffold(
      body: content,
      bottomNavigationBar: NavigationBar(
        selectedIndex: _index,
        onDestinationSelected: (i) => setState(() => _index = i),
        destinations: _destinations,
      ),
    );
  }
}

class _RailHeader extends StatelessWidget {
  const _RailHeader();

  @override
  Widget build(BuildContext context) {
    return const SizedBox(
      height: 96,
      child: Center(
        child: Tooltip(message: 'AMR Controller', child: Icon(Icons.precision_manufacturing)),
      ),
    );
  }
}