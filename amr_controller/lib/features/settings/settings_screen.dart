// Settings — locally-persisted operator preferences. No robot secrets stored
// here (there is no auth); only connection + display preferences.

import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../providers/robot_provider.dart';
import '../../theme/theme.dart';
import '../../widgets/status_widgets.dart';

class SettingsScreen extends StatelessWidget {
  const SettingsScreen({super.key});

  @override
  Widget build(BuildContext context) {
    final p = context.watch<RobotProvider>();

    return SingleChildScrollView(
      padding: const EdgeInsets.all(20),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const SectionHeader(title: 'Settings'),
          const SizedBox(height: 8),
          Container(
            padding: const EdgeInsets.all(14),
            decoration: BoxDecoration(
              color: AppPalette.surface,
              border: Border.all(color: AppPalette.line),
              borderRadius: BorderRadius.circular(10),
            ),
            child: Column(
              children: [
                SwitchListTile(
                  title: const Text('Simulation mode'),
                  subtitle: const Text('Explore the UI with no robot (never issues commands)'),
                  value: p.simulation,
                  onChanged: (v) => context.read<RobotProvider>().setSimulation(v),
                ),
                const Divider(height: 1),
                SwitchListTile(
                  title: const Text('Auto-reconnect'),
                  subtitle: const Text('Re-probe the robot if the link drops'),
                  value: p.autoReconnect,
                  onChanged: (v) => context.read<RobotProvider>().setAutoReconnect(v),
                ),
                const Divider(height: 1),
                const ListTile(
                  title: Text('Robot address'),
                  subtitle: Text('Edit from the Connection screen'),
                  dense: true,
                ),
              ],
            ),
          ),
          const SizedBox(height: 20),
          const SectionHeader(title: 'Key bindings'),
          const Text(
            'W/S = forward/reverse · A/D = rotate · Space = stop · E = E-STOP (desktop only)',
            style: TextStyle(color: AppPalette.muted, fontSize: 12),
          ),
        ],
      ),
    );
  }
}