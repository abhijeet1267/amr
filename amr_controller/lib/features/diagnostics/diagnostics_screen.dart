// Diagnostics — a professional subsystem health console assembled from real
// telemetry + health + connectivity. Green=healthy, amber=warning, red=fault,
// grey=unavailable. No subsystem is asserted healthy without data.

import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../providers/robot_provider.dart';
import '../../theme/theme.dart';
import '../../widgets/status_widgets.dart';

class DiagnosticsScreen extends StatelessWidget {
  const DiagnosticsScreen({super.key});

  @override
  Widget build(BuildContext context) {
    final p = context.watch<RobotProvider>();
    final t = p.telemetry;

    return SingleChildScrollView(
      padding: const EdgeInsets.all(20),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              const Expanded(child: SectionHeader(title: 'Diagnostics')),
              OutlinedButton.icon(
                onPressed: () => p.ping(),
                icon: const Icon(Icons.sync, size: 16),
                label: const Text('Refresh'),
              ),
            ],
          ),
          const SizedBox(height: 8),
          _diag(context, 'Network', p.isConnected, Icons.wifi),
          _diag(context, 'API', p.isConnected, Icons.api),
          _diag(context, 'Telemetry', t != null, Icons.timeline),
          _diag(context, 'Camera', p.camera?.isLive == true, Icons.videocam),
          _diag(context, 'Sensors', (t?.frontCm ?? 0) > 0, Icons.sensors),
          _diag(context, 'Map', p.map?.robot != null, Icons.map),
          _diag(context, 'Battery', t?.batteryPercentage != null, Icons.battery_full),
          const _DiagRow('CPU', 'not available (not exposed)', AppPalette.dim, Icons.memory),
          const _DiagRow('Memory', 'not available (not exposed)', AppPalette.dim, Icons.sd_storage),
          const _DiagRow('Storage', 'not available (not exposed)', AppPalette.dim, Icons.storage),
        ],
      ),
    );
  }

  Widget _diag(BuildContext context, String name, bool healthy, IconData icon) {
    return _DiagRow(
      name,
      healthy ? 'healthy' : 'unavailable / not connected',
      healthy ? AppPalette.ok : AppPalette.warn,
      icon,
    );
  }
}

class _DiagRow extends StatelessWidget {
  const _DiagRow(this.name, this.detail, this.colour, this.icon);

  final String name;
  final String detail;
  final Color colour;
  final IconData icon;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 4),
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
        decoration: BoxDecoration(
          color: AppPalette.surface,
          border: Border.all(color: AppPalette.line),
          borderRadius: BorderRadius.circular(8),
        ),
        child: Row(
          children: [
            Icon(icon, size: 18, color: colour),
            const SizedBox(width: 12),
            SizedBox(width: 100, child: Text(name, style: const TextStyle(color: AppPalette.text, fontWeight: FontWeight.w600))),
            Expanded(child: Text(detail, style: const TextStyle(color: AppPalette.muted, fontSize: 12))),
            StatusPill(label: colour == AppPalette.ok ? 'HEALTHY' : 'UNAVAILABLE', colour: colour, dot: false),
          ],
        ),
      ),
    );
  }
}