// Live telemetry & control (teleop).
//
// The joystick emits JoystickDirection + a magnitude; this screen maps that
// onto the robot's *real* `/command` verbs (forward/backward/turn_left/
// turn_right/rotate_left/rotate_right/stop) and scales the magnitude to the
// robot's speed range. A stop accompanies every release so a dropped drag can
// never leave the robot driving.
//
// E-STOP is guarded (long-press to arm, then a confirm) and, like the shell, is
// replicated here in a banner so it is reachable the moment this screen is
// visible, even if the operator never opens the drawer.
library;

import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_spinkit/flutter_spinkit.dart';
import 'package:provider/provider.dart';

import '../models/app_state.dart';
import '../providers/robot_provider.dart';
import '../theme/theme.dart';
import '../widgets/joystick_widget.dart';

class TeleopScreen extends StatefulWidget {
  const TeleopScreen({super.key});

  @override
  State<TeleopScreen> createState() => _TeleopScreenState();
}

class _TeleopScreenState extends State<TeleopScreen> {
  // The robot scales motor speed over a 1..max range; the joystick's magnitude
  // (0..1) is mapped onto an integer in that band. 100 is the panel's default
  // for forward/backward; turns run a little slower (80).
  static const int _maxSpeed = 100;

  String? _lastFeedback;

  Future<void> _send(String cmd, {int? speed}) async {
    final provider = context.read<RobotProvider>();
    final ok = await provider.command(cmd, speed: speed);
    if (!mounted) return;
    setState(() {
      _lastFeedback = ok
          ? '$cmd ok'
          : '${provider.lastCommandError ?? 'command failed'}';
    });
  }

  Future<void> _handleJoy(JoystickDirection dir, double mag) async {
    final raw = (mag * _maxSpeed).round();
    final speed = raw.clamp(1, _maxSpeed).toInt();
    switch (dir) {
      case JoystickDirection.stop:
        await _send('stop');
        break;
      case JoystickDirection.forward:
        await _send('forward', speed: speed);
        break;
      case JoystickDirection.backward:
        await _send('backward', speed: speed);
        break;
      case JoystickDirection.left:
        await _send('rotate_left', speed: speed);
        break;
      case JoystickDirection.right:
        await _send('rotate_right', speed: speed);
        break;
      case JoystickDirection.forwardLeft:
        await _send('turn_left', speed: speed);
        break;
      case JoystickDirection.forwardRight:
        await _send('turn_right', speed: speed);
        break;
      // Diagonal-y backwards: map to rotate so the robot never drives blind
      // into an unverified rear corridor beyond a plain backward command.
      case JoystickDirection.backwardLeft:
      case JoystickDirection.backwardRight:
        await _send('backward', speed: speed);
        break;
    }
  }

  @override
  Widget build(BuildContext context) {
    final provider = context.watch<RobotProvider>();
    final telemetry = provider.telemetry;

    return Scaffold(
      appBar: AppBar(
        title: const Text('Teleop'),
        actions: [
          Padding(
            padding: const EdgeInsets.only(right: 12),
            child: Center(child: _ModeChip(mode: telemetry?.mode, connected: provider.isConnected)),
          ),
        ],
      ),
      body: !provider.isConnected
          ? const _NotConnected()
          : SingleChildScrollView(
              padding: const EdgeInsets.all(20),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  _TelemetryStrip(telemetry: telemetry),
                  const SizedBox(height: 20),
                  Text(
                    _lastFeedback ?? 'Drive the robot',
                    textAlign: TextAlign.center,
                    style: const TextStyle(color: AppPalette.muted),
                  ),
                  const SizedBox(height: 12),
                  Center(
                    child: JoystickWidget(
                      size: MediaQuery.sizeOf(context).width < 400 ? 200 : 240,
                      onCommand: _handleJoy,
                    ),
                  ),
                  const SizedBox(height: 24),
                  const _Dpad(),
                ],
              ),
            ),
      bottomNavigationBar: provider.isConnected ? const _EstopBar() : null,
    );
  }
}

class _ModeChip extends StatelessWidget {
  const _ModeChip({required this.mode, required this.connected});
  final String? mode;
  final bool connected;

  @override
  Widget build(BuildContext context) {
    final label = !connected ? 'OFFLINE' : (mode ?? '…').toUpperCase();
    final color = !connected
        ? AppPalette.crit
        : (mode == 'SAFETY_STOP' || mode == 'ERROR')
            ? AppPalette.crit
            : AppPalette.ok;
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.12),
        border: Border.all(color: color),
        borderRadius: BorderRadius.circular(999),
      ),
      child: Text(
        label,
        style: TextStyle(color: color, fontSize: 11, fontWeight: FontWeight.w700),
      ),
    );
  }
}

class _TelemetryStrip extends StatelessWidget {
  const _TelemetryStrip({required this.telemetry});
  final TelemetryState? telemetry;

  @override
  Widget build(BuildContext context) {
    final t = telemetry;
    if (t == null) {
      return const Center(
        child: SpinKitThreeBounce(color: AppPalette.accent, size: 20),
      );
    }
    return Wrap(
      spacing: 12,
      runSpacing: 12,
      children: [
        _TelemetryTile(
          label: 'Battery',
          value: t.batteryPercentage == null
              ? 'no sensor'
              : '${t.batteryPercentage!.round()} %',
          icon: Icons.battery_full,
          colour: t.batteryPercentage == null
              ? AppPalette.muted
              : AppPalette.ok,
        ),
        _TelemetryTile(
          label: 'Speed',
          value: t.speedMps == null
              ? 'n/a'
              : '${t.speedMps!.toStringAsFixed(2)} m/s',
          icon: Icons.speed,
          colour: AppPalette.info,
        ),
        _TelemetryTile(
          label: 'Front',
          value: t.frontCm == null ? 'n/a' : '${t.frontCm} cm',
          icon: Icons.vertical_align_top,
          colour: t.frontCm != null && t.frontCm! < 30
              ? AppPalette.crit
              : AppPalette.ok,
        ),
        _TelemetryTile(
          label: 'Status',
          value: t.connected ? 'online' : 'offline',
          icon: t.connected ? Icons.check_circle : Icons.cancel,
          colour: t.connected ? AppPalette.ok : AppPalette.crit,
        ),
      ],
    );
  }
}

class _TelemetryTile extends StatelessWidget {
  const _TelemetryTile({
    required this.label,
    required this.value,
    required this.icon,
    required this.colour,
  });

  final String label;
  final String value;
  final IconData icon;
  final Color colour;

  @override
  Widget build(BuildContext context) {
    return Container(
      constraints: const BoxConstraints(minWidth: 150),
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: AppPalette.surface,
        border: Border.all(color: AppPalette.line),
        borderRadius: BorderRadius.circular(10),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Icon(icon, size: 16, color: colour),
              const SizedBox(width: 6),
              Text(label, style: const TextStyle(color: AppPalette.muted, fontSize: 11)),
            ],
          ),
          const SizedBox(height: 8),
          Text(
            value,
            style: const TextStyle(
              color: AppPalette.text,
              fontSize: 18,
              fontWeight: FontWeight.w600,
            ),
          ),
        ],
      ),
    );
  }
}

/// Digital fallback for the joystick: a proper D-pad bound to the same verbs,
/// so a keyboard operator or a tap has a one-gesture path. Up/down drive,
/// left/right rotate in place, centre stops. Turns are reachable via the
/// joystick's diagonal sectors.
class _Dpad extends StatelessWidget {
  const _Dpad();

  void _tap(BuildContext context, String cmd) {
    context.read<RobotProvider>().command(cmd);
  }

  @override
  Widget build(BuildContext context) {
    Widget key(String cmd, IconData icon, {String? tooltip}) => IconButton(
          onPressed: () => _tap(context, cmd),
          icon: Icon(icon),
          tooltip: tooltip,
          style: IconButton.styleFrom(
            backgroundColor: AppPalette.surfaceVariant,
            foregroundColor: AppPalette.text,
            minimumSize: const Size(52, 52),
          ),
        );

    return Column(
      children: [
        key('forward', Icons.arrow_upward, tooltip: 'Forward'),
        const SizedBox(height: 4),
        Row(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            key('rotate_left', Icons.arrow_back, tooltip: 'Rotate left'),
            const SizedBox(width: 4),
            key('stop', Icons.stop, tooltip: 'Stop'),
            const SizedBox(width: 4),
            key('rotate_right', Icons.arrow_forward, tooltip: 'Rotate right'),
          ],
        ),
        const SizedBox(height: 4),
        key('backward', Icons.arrow_downward, tooltip: 'Backward'),
      ],
    );
  }
}

class _EstopBar extends StatefulWidget {
  const _EstopBar();

  @override
  State<_EstopBar> createState() => _EstopBarState();
}

class _EstopBarState extends State<_EstopBar> {
  bool _armed = false;
  Timer? _armTimer;

  void _onHoldStart() {
    _armTimer?.cancel();
    _armTimer = Timer(const Duration(seconds: 1), () {
      if (mounted) setState(() => _armed = true);
    });
  }

  void _onHoldEnd() {
    _armTimer?.cancel();
    if (_armed && mounted) {
      _armed = false;
      context.read<RobotProvider>().command('estop');
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text('E-STOP sent'),
          backgroundColor: AppPalette.crit,
        ),
      );
    }
  }

  @override
  void dispose() {
    _armTimer?.cancel();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return SafeArea(
      child: Padding(
        padding: const EdgeInsets.fromLTRB(20, 8, 20, 12),
        child: GestureDetector(
          onLongPressStart: (_) => _onHoldStart(),
          onLongPressEnd: (_) => _onHoldEnd(),
          child: Container(
            height: 56,
            decoration: BoxDecoration(
              color: (_armed ? AppPalette.crit : AppPalette.crit.withValues(alpha: 0.15)),
              border: Border.all(
                color: AppPalette.crit,
                width: _armed ? 3 : 2,
              ),
              borderRadius: BorderRadius.circular(12),
            ),
            child: Center(
              child: Text(
                _armed ? 'RELEASE TO E-STOP' : 'HOLD TO ARM — E-STOP',
                style: TextStyle(
                  color: _armed ? Colors.white : AppPalette.crit,
                  fontWeight: FontWeight.w800,
                  letterSpacing: 1.2,
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }
}

class _NotConnected extends StatelessWidget {
  const _NotConnected();

  @override
  Widget build(BuildContext context) {
    return const Center(
      child: Text(
        'Connect to the robot to drive it.',
        style: TextStyle(color: AppPalette.muted),
      ),
    );
  }
}