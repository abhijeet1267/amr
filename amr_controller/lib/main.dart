// AMR Controller — app entry point.
//
// Owns the MaterialApp, the shared theme, the provider injection, and the
// responsive navigation shell. Desktop gets a rail-tabbed multi-panel command
// center; mobile gets a bottom NavigationBar over the same destinations.

import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import 'features/camera/camera_screen.dart';
import 'features/dashboard/dashboard_screen.dart';
import 'features/diagnostics/diagnostics_screen.dart';
import 'features/logs/logs_screen.dart';
import 'features/map/map_screen.dart';
import 'features/missions/missions_screen.dart';
import 'features/sensors/sensors_screen.dart';
import 'features/settings/settings_screen.dart';
import 'providers/robot_provider.dart';
import 'screens/applications_hub_screen.dart';
import 'screens/connection_screen.dart';
import 'screens/teleop_screen.dart';
import 'theme/theme.dart';
import 'widgets/console_rail.dart';
import 'widgets/status_widgets.dart';

void main() {
  WidgetsFlutterBinding.ensureInitialized();
  runApp(const AmrControllerApp());
}

class AmrControllerApp extends StatelessWidget {
  const AmrControllerApp({super.key, this.provider});

  final RobotProvider? provider;

  @override
  Widget build(BuildContext context) {
    return ChangeNotifierProvider(
      create: (_) => (provider ?? RobotProvider())..loadSavedConnection(),
      child: MaterialApp(
        title: 'AMR Controller',
        debugShowCheckedModeBanner: false,
        theme: buildAppTheme(),
        home: const CommandCenterShell(),
      ),
    );
  }
}

/// The navigation shell. Desktop > 800px uses a NavigationRail; mobile uses a
/// bottom NavigationBar. Every screen reads the single provider via context.
class CommandCenterShell extends StatefulWidget {
  const CommandCenterShell({super.key});

  @override
  State<CommandCenterShell> createState() => _CommandCenterShellState();
}

class _CommandCenterShellState extends State<CommandCenterShell> {
  int _index = 0;

  static const _items = [
    (Icons.dashboard_outlined, Icons.dashboard, 'Dashboard'),
    (Icons.videocam_outlined, Icons.videocam, 'Camera'),
    (Icons.map_outlined, Icons.map, 'Map'),
    (Icons.gamepad_outlined, Icons.gamepad, 'Teleop'),
    (Icons.alt_route, Icons.alt_route, 'Missions'),
    (Icons.hub_outlined, Icons.hub, 'Apps'),
    (Icons.sensors, Icons.sensors, 'Sensors'),
    (Icons.monitor_heart_outlined, Icons.monitor_heart, 'Diagnostics'),
    (Icons.article_outlined, Icons.article, 'Logs'),
    (Icons.settings_outlined, Icons.settings, 'Settings'),
    (Icons.settings_input_component_outlined, Icons.settings_input_component, 'Connection'),
  ];

  static const _screens = <Widget>[
    DashboardScreen(),
    CameraScreen(),
    MapScreen(),
    TeleopScreen(),
    MissionsScreen(),
    ApplicationsHubScreen(),
    SensorsScreen(),
    DiagnosticsScreen(),
    LogsScreen(),
    SettingsScreen(),
    ConnectionScreen(),
  ];

  @override
  Widget build(BuildContext context) {
    final sim = context.select<RobotProvider, bool>((p) => p.simulation);
    final alerts = context.select<RobotProvider, List<OperatorAlert>>((p) => p.alerts);
    final isWide = MediaQuery.sizeOf(context).width >= 800;

    return Scaffold(
      body: Column(
        children: [
          if (sim) const SimulationBanner(),
          if (alerts.isNotEmpty) _AlertStrip(alerts: alerts),
          Expanded(
            child: isWide
                ? Row(
                    children: [
                      ConsoleRail(
                        index: _index,
                        onSelect: (i) => setState(() => _index = i),
                        items: _items,
                      ),
                      const VerticalDivider(width: 1),
                      Expanded(child: _screens[_index]),
                    ],
                  )
                : Column(
                    children: [
                      Expanded(child: _screens[_index]),
                      NavigationBar(
                        selectedIndex: _index,
                        onDestinationSelected: (i) => setState(() => _index = i),
                        destinations: [
                          for (final (ic, icSel, label) in _items.take(5))
                            NavigationDestination(
                              icon: Icon(ic),
                              selectedIcon: Icon(icSel),
                              label: label,
                            ),
                        ],
                      ),
                    ],
                  ),
          ),
        ],
      ),
    );
  }
}

/// Non-intrusive operator alert strip — critical first, most recent within a
/// severity last. Colour is never the only signal: each alert prints its text.
class _AlertStrip extends StatelessWidget {
  const _AlertStrip({required this.alerts});

  final List<OperatorAlert> alerts;

  @override
  Widget build(BuildContext context) {
    final sorted = [...alerts]..sort((a, b) => b.severity.index.compareTo(a.severity.index));
    return Container(
      width: double.infinity,
      color: AppPalette.surfaceVariant,
      padding: const EdgeInsets.symmetric(vertical: 4, horizontal: 12),
      child: Wrap(
        spacing: 12,
        runSpacing: 4,
        children: [
          for (final a in sorted)
            Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                Icon(
                  a.severity == AlertSeverity.critical
                      ? Icons.error
                      : Icons.warning_amber,
                  size: 13,
                  color: a.severity == AlertSeverity.critical
                      ? AppPalette.crit
                      : AppPalette.warn,
                ),
                const SizedBox(width: 5),
                Text(
                  a.message,
                  style: TextStyle(
                    fontSize: 11,
                    fontWeight: FontWeight.w600,
                    color: a.severity == AlertSeverity.critical
                        ? AppPalette.crit
                        : AppPalette.warn,
                  ),
                ),
              ],
            ),
        ],
      ),
    );
  }
}