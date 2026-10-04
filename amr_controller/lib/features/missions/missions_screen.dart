// Missions — the mission/waypoint planner.
//
// IMPORTANT: the backend has NO autonomous navigation, waypoint, or mission
// command. The `/command` surface is estop/stop/mode/motion only (verified in
// server.py). So the START/PAUSE/RESUME/ABORT/RETURN controls are built as the
// UI + abstraction, but are gated and honest: they are disabled with an
// explanatory note until the backend exposes a mission endpoint. This does not
// fake execution.

import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../models/app_state.dart';
import '../../providers/robot_provider.dart';
import '../../theme/theme.dart';
import '../../widgets/status_widgets.dart';

class MissionsScreen extends StatelessWidget {
  const MissionsScreen({super.key});

  @override
  Widget build(BuildContext context) {
    final p = context.watch<RobotProvider>();

    // Missions whose category is "demo" are runnable terminal commands from the
    // registry; surface them as the honest "what can actually be run" list.
    final demos = (p.registry?.applications ?? const <AppState>[])
        .where((a) => a.category == 'demo' && a.launchCommand != null)
        .toList();

    return SingleChildScrollView(
      padding: const EdgeInsets.all(20),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const SectionHeader(title: 'Mission'),
          Container(
            padding: const EdgeInsets.all(14),
            decoration: BoxDecoration(
              color: AppPalette.surface,
              border: Border.all(color: AppPalette.line),
              borderRadius: BorderRadius.circular(10),
            ),
            child: const Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  'Autonomous mission control is not available on this backend.',
                  style: TextStyle(color: AppPalette.warn, fontSize: 13, fontWeight: FontWeight.w700),
                ),
                SizedBox(height: 6),
                Text(
                  'The robot exposes motion/mode/E-STOP commands only; there is no '
                  'navigate/waypoint/mission endpoint. These controls are disabled '
                  'until a mission API is added to the robot server.',
                  style: TextStyle(color: AppPalette.muted, fontSize: 12),
                ),
              ],
            ),
          ),
          const SizedBox(height: 12),
          const Wrap(
            spacing: 8,
            runSpacing: 8,
            children: [
              _DisabledBtn('Start'),
              _DisabledBtn('Pause'),
              _DisabledBtn('Resume'),
              _DisabledBtn('Abort'),
              _DisabledBtn('Return to dock'),
            ],
          ),
          const SizedBox(height: 20),
          const SectionHeader(title: 'Runnable demos (from registry)'),
          if (demos.isEmpty)
            const Text('No runnable demos registered', style: TextStyle(color: AppPalette.dim))
          else
            for (final d in demos)
              Padding(
                padding: const EdgeInsets.symmetric(vertical: 4),
                child: Container(
                  padding: const EdgeInsets.all(12),
                  decoration: BoxDecoration(
                    color: AppPalette.surfaceVariant,
                    border: Border.all(color: AppPalette.line),
                    borderRadius: BorderRadius.circular(8),
                  ),
                  child: Row(
                    children: [
                      Expanded(
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Text(d.name, style: const TextStyle(color: AppPalette.text, fontWeight: FontWeight.w600)),
                            Text(
                              d.launchCommand ?? '',
                              style: const TextStyle(color: AppPalette.accent, fontSize: 11, fontFamily: 'monospace'),
                            ),
                          ],
                        ),
                      ),
                      StatusPill(label: d.status, colour: statusColour(d.status)),
                    ],
                  ),
                ),
              ),
        ],
      ),
    );
  }
}

class _DisabledBtn extends StatelessWidget {
  const _DisabledBtn(this.label);

  final String label;

  @override
  Widget build(BuildContext context) {
    return OutlinedButton(
      onPressed: null,
      child: Text(label),
    );
  }
}