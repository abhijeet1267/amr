// Sensors — live distance/ultrasonic readouts from the REAL telemetry.
//
// The robot has four HC-SR04 ultrasonic sensors (F/L/R/B). There is no LiDAR,
// IMU, encoder, GPS or collision-sensor exposure in the backend, so those are
// shown as "not available" rather than fabricated.

import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../providers/robot_provider.dart';
import '../../theme/theme.dart';
import '../../widgets/status_widgets.dart';

class SensorsScreen extends StatelessWidget {
  const SensorsScreen({super.key});

  @override
  Widget build(BuildContext context) {
    final provider = context.watch<RobotProvider>();
    final t = provider.telemetry;

    Widget dist(String label, int? cm, IconData icon) {
      final near = cm != null && cm < 30;
      return MetricTile(
        label: label,
        value: cm == null ? '—' : '$cm',
        unit: cm == null ? null : 'cm',
        icon: icon,
        colour: cm == null ? AppPalette.dim : (near ? AppPalette.crit : AppPalette.ok),
      );
    }

    return SingleChildScrollView(
      padding: const EdgeInsets.all(20),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const SectionHeader(title: 'Distance Sensors'),
          Wrap(
            spacing: 12,
            runSpacing: 12,
            children: [
              dist('FRONT', t?.frontCm, Icons.arrow_upward),
              dist('LEFT', t?.leftCm, Icons.arrow_back),
              dist('RIGHT', t?.rightCm, Icons.arrow_forward),
              dist('REAR', t?.rearCm, Icons.arrow_downward),
            ],
          ),
          const SizedBox(height: 20),
          const SectionHeader(title: 'Other Sensors'),
          const Wrap(
            spacing: 12,
            runSpacing: 12,
            children: [
              MetricTile(label: 'LiDAR', value: '—', icon: Icons.radar, colour: AppPalette.dim),
              MetricTile(label: 'IMU', value: '—', icon: Icons.gps_fixed, colour: AppPalette.dim),
              MetricTile(label: 'Encoder', value: '—', icon: Icons.settings, colour: AppPalette.dim),
              MetricTile(label: 'GPS', value: '—', icon: Icons.pin_drop, colour: AppPalette.dim),
              MetricTile(label: 'Camera', value: '—', icon: Icons.videocam, colour: AppPalette.dim),
            ],
          ),
          const SizedBox(height: 20),
          const Text(
            'The AMR exposes 4 ultrasonic sensors. LiDAR/IMU/encoder/GPS/collision '
            'sensors are not present in this robot, so they read unavailable.',
            style: TextStyle(color: AppPalette.dim, fontSize: 11),
          ),
        ],
      ),
    );
  }
}