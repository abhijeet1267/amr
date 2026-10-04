// Dashboard — the operator's home screen. A live summary of robot identity,
// connection, mode, power, velocity, E-STOP, obstacle, camera and navigation
// state, assembled from the real telemetry/map/connectivity the provider polls.
//
// Where the backend does not expose a value (there is no CPU/robot temperature,
// no GPS, no LiDAR in this robot), the tile shows "not available" rather than a
// fabricated number. Simulation mode is clearly labelled by the shell banner.

import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../core/format.dart';
import '../../providers/robot_provider.dart';
import '../../theme/theme.dart';
import '../../widgets/status_widgets.dart';

class DashboardScreen extends StatelessWidget {
  const DashboardScreen({super.key});

  @override
  Widget build(BuildContext context) {
    final provider = context.watch<RobotProvider>();
    final t = provider.telemetry;
    final online = provider.isConnected;

    final battery = t?.batteryPercentage;
    final voltage = t?.batteryVoltage;
    final speed = t?.speedMps;
    final estop = t?.emergencyStop ?? false;

    return SingleChildScrollView(
      padding: const EdgeInsets.all(20),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          // --- robot status header ---
          _StatusHeader(
            online: online,
            mode: t?.mode ?? (online ? '—' : 'OFFLINE'),
            battery: battery,
            latencyMs: provider.latencyMs,
            estop: estop,
            cameraLive: provider.camera?.isLive ?? false,
            simulation: provider.simulation,
          ),
          const SizedBox(height: 20),
          // --- power ---
          const SectionHeader(title: 'Power'),
          Wrap(
            spacing: 12,
            runSpacing: 12,
            children: [
              MetricTile(
                label: 'Battery',
                value: battery == null ? '—' : battery.round().toString(),
                unit: battery == null ? null : '%',
                icon: Icons.battery_full,
                colour: battery == null
                    ? AppPalette.dim
                    : battery < 20
                        ? AppPalette.crit
                        : AppPalette.ok,
              ),
              MetricTile(
                label: 'Voltage',
                value: voltage == null ? '—' : voltage.toStringAsFixed(1),
                unit: voltage == null ? null : 'V',
                icon: Icons.bolt,
                colour: AppPalette.info,
              ),
              const MetricTile(
                label: 'CPU Temp',
                value: '—',
                icon: Icons.thermostat,
                colour: AppPalette.dim,
              ),
              const MetricTile(
                label: 'Robot Temp',
                value: '—',
                icon: Icons.device_thermostat,
                colour: AppPalette.dim,
              ),
            ],
          ),
          const SizedBox(height: 20),
          // --- motion ---
          const SectionHeader(title: 'Motion'),
          Wrap(
            spacing: 12,
            runSpacing: 12,
            children: [
              MetricTile(
                label: 'Linear',
                value: speed == null ? '—' : speed.toStringAsFixed(2),
                unit: speed == null ? null : 'm/s',
                icon: Icons.straighten,
                colour: AppPalette.accent,
              ),
              const MetricTile(
                label: 'Angular',
                value: '—',
                icon: Icons.rotate_right,
                colour: AppPalette.dim,
              ),
              MetricTile(
                label: 'Obstacle (front)',
                value: t?.frontCm == null ? '—' : '${t!.frontCm} cm',
                icon: Icons.sensors,
                colour: (t?.frontCm ?? 999) < 30 ? AppPalette.crit : AppPalette.ok,
              ),
            ],
          ),
          const SizedBox(height: 20),
          // --- safety & health ---
          const SectionHeader(title: 'Safety / Health'),
          Wrap(
            spacing: 12,
            runSpacing: 12,
            children: [
              MetricTile(
                label: 'E-STOP',
                value: estop ? 'ACTIVE' : 'ARMED',
                icon: estop ? Icons.warning : Icons.shield,
                colour: estop ? AppPalette.crit : AppPalette.ok,
              ),
              MetricTile(
                label: 'Camera',
                value: provider.camera?.isLive == true ? 'ONLINE' : 'OFFLINE',
                icon: provider.camera?.isLive == true
                    ? Icons.videocam
                    : Icons.videocam_off,
                colour: provider.camera?.isLive == true
                    ? AppPalette.ok
                    : AppPalette.dim,
              ),
              MetricTile(
                label: 'Navigation',
                value: provider.map?.navigationState ?? '—',
                icon: Icons.route,
                colour: AppPalette.info,
              ),
            ],
          ),
          const SizedBox(height: 20),
          // --- nav / battery trend summary block ---
          SectionHeader(
            title: 'Robot',
            trailing: Text(
              'robot_id ${t?.robotId ?? '—'}',
              style: const TextStyle(color: AppPalette.dim, fontSize: 10),
            ),
          ),
          KvRow(label: 'IP Address', value: provider.host),
          KvRow(label: 'Control', value: provider.simulation ? 'SIMULATION' : (online ? 'LIVE' : 'OFFLINE')),
          KvRow(label: 'Last update', value: provider.lastUpdateMs == null ? '—' : fmtClock(provider.lastUpdateMs)),
          KvRow(label: 'Source', value: t?.simulated == true ? 'SIMULATION' : 'LIVE'),
        ],
      ),
    );
  }
}

class _StatusHeader extends StatelessWidget {
  const _StatusHeader({
    required this.online,
    required this.mode,
    required this.battery,
    required this.latencyMs,
    required this.estop,
    required this.cameraLive,
    required this.simulation,
  });

  final bool online;
  final String mode;
  final double? battery;
  final int? latencyMs;
  final bool estop;
  final bool cameraLive;
  final bool simulation;

  @override
  Widget build(BuildContext context) {
    final connColour = !online
        ? AppPalette.crit
        : simulation
            ? AppPalette.warn
            : AppPalette.ok;
    final b = battery;
    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: AppPalette.surface,
        border: Border.all(color: AppPalette.line),
        borderRadius: BorderRadius.circular(10),
      ),
      child: Wrap(
        spacing: 16,
        runSpacing: 10,
        crossAxisAlignment: WrapCrossAlignment.center,
        children: [
          const Text(
            'AMR CONTROL CENTER',
            style: TextStyle(
              color: AppPalette.gold,
              fontWeight: FontWeight.w800,
              letterSpacing: 1,
              fontSize: 15,
            ),
          ),
          StatusPill(label: online ? 'ONLINE' : 'OFFLINE', colour: connColour),
          StatusPill(label: mode, colour: AppPalette.info),
          StatusPill(
            label: b == null ? 'BATTERY —' : 'BATTERY ${b.round()}%',
            colour: b == null
                ? AppPalette.dim
                : b < 20
                    ? AppPalette.crit
                    : AppPalette.ok,
          ),
          StatusPill(
            label: 'LATENCY ${fmtLatency(latencyMs)}',
            colour: latencyMs == null ? AppPalette.dim : AppPalette.muted,
          ),
          StatusPill(label: estop ? 'E-STOP ACTIVE' : 'E-STOP ARMED', colour: estop ? AppPalette.crit : AppPalette.ok),
          StatusPill(label: cameraLive ? 'CAMERA ONLINE' : 'CAMERA OFFLINE', colour: cameraLive ? AppPalette.ok : AppPalette.dim),
        ],
      ),
    );
  }
}