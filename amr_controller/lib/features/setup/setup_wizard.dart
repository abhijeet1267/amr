// First-run setup & preflight wizard.
//
// This app drives a physical robot, so "connected" is not the same as "safe to
// drive". The wizard runs before the console is reachable and walks the
// operator through the three failure classes that actually happen in the field:
//
//   1. the robot is not reachable at all          -> Connect step
//   2. reachable, but a sub-system is down        -> Connect step (per-endpoint)
//   3. reachable and healthy, but a precondition
//      for safe motion is unmet                   -> Checks step (fatal/warning)
//
// It reuses the console's own widgets so it reads as part of the product, and
// it never invents a reading: an absent sensor prints "not available", and a
// `-1` ultrasonic reading is shown as "clear" (no echo), never as 0 cm.

import 'package:flutter/material.dart';
import 'package:flutter_spinkit/flutter_spinkit.dart';
import 'package:provider/provider.dart';

import '../../models/app_state.dart';
import '../../providers/robot_provider.dart';
import '../../theme/theme.dart';
import '../../widgets/status_widgets.dart';

class SetupWizard extends StatefulWidget {
  const SetupWizard({super.key, this.onFinished});

  /// Called when setup is complete. In first-run use this swaps the app over to
  /// the console; when the wizard is pushed, the caller pops instead.
  final VoidCallback? onFinished;

  @override
  State<SetupWizard> createState() => _SetupWizardState();
}

class _SetupWizardState extends State<SetupWizard> {
  int _step = 0;
  late final TextEditingController _host;

  static const _titles = ['Welcome', 'Connect', 'Checks', 'Ready'];

  @override
  void initState() {
    super.initState();
    _host = TextEditingController(text: context.read<RobotProvider>().host);
  }

  @override
  void dispose() {
    _host.dispose();
    super.dispose();
  }

  Future<void> _runTest() async {
    final p = context.read<RobotProvider>();
    await p.saveHost(_host.text);
    await p.runDiagnostics();
  }

  void _finish() {
    if (widget.onFinished != null) {
      widget.onFinished!();
    } else {
      Navigator.of(context).maybePop();
    }
  }

  @override
  Widget build(BuildContext context) {
    final p = context.watch<RobotProvider>();
    final preflight = p.preflight();
    final fatal = preflight.where((i) => i.severity == PreflightSeverity.fatal).toList();

    // Advancing out of the Connect step requires every *required* endpoint to
    // have answered; out of Checks, no fatal precondition may remain.
    final canAdvance = switch (_step) {
      1 => p.coreEndpointsOk,
      2 => fatal.isEmpty,
      _ => true,
    };

    return Scaffold(
      appBar: AppBar(
        title: const Text('Robot setup'),
        actions: [
          if (_step < 3)
            TextButton(
              onPressed: () async {
                await context.read<RobotProvider>().markSetupComplete();
                _finish();
              },
              child: const Text('Skip'),
            ),
        ],
      ),
      body: Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 780),
          child: Column(
            children: [
              _StepBar(step: _step, titles: _titles),
              const Divider(height: 1),
              Expanded(
                child: SingleChildScrollView(
                  padding: const EdgeInsets.all(20),
                  child: switch (_step) {
                    0 => const _WelcomeStep(),
                    1 => _ConnectStep(
                        controller: _host,
                        provider: p,
                        onRun: _runTest,
                      ),
                    2 => _ChecksStep(items: preflight),
                    _ => _ReadyStep(provider: p, onFinish: _finish),
                  },
                ),
              ),
              const Divider(height: 1),
              _NavBar(
                step: _step,
                canAdvance: canAdvance,
                onBack: _step == 0 ? null : () => setState(() => _step -= 1),
                onNext: _step == 3
                    ? null
                    : () => setState(() => _step += 1),
                onFinish: _finish,
              ),
            ],
          ),
        ),
      ),
    );
  }
}

// ---------------------------------------------------------------------------
// Step indicator
// ---------------------------------------------------------------------------

class _StepBar extends StatelessWidget {
  const _StepBar({required this.step, required this.titles});

  final int step;
  final List<String> titles;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 14),
      child: Row(
        children: [
          for (var i = 0; i < titles.length; i++) ...[
            _StepDot(index: i, active: i == step, done: i < step, label: titles[i]),
            if (i < titles.length - 1)
              Expanded(
                child: Container(
                  height: 2,
                  margin: const EdgeInsets.symmetric(horizontal: 8),
                  color: i < step ? AppPalette.accent : AppPalette.line,
                ),
              ),
          ],
        ],
      ),
    );
  }
}

class _StepDot extends StatelessWidget {
  const _StepDot({
    required this.index,
    required this.active,
    required this.done,
    required this.label,
  });

  final int index;
  final bool active;
  final bool done;
  final String label;

  @override
  Widget build(BuildContext context) {
    final colour = done || active ? AppPalette.accent : AppPalette.dim;
    return Column(
      mainAxisSize: MainAxisSize.min,
      children: [
        Container(
          width: 26,
          height: 26,
          alignment: Alignment.center,
          decoration: BoxDecoration(
            color: done ? AppPalette.accent : Colors.transparent,
            border: Border.all(color: colour, width: 2),
            shape: BoxShape.circle,
          ),
          child: done
              ? const Icon(Icons.check, size: 15, color: Colors.white)
              : Text(
                  '${index + 1}',
                  style: TextStyle(
                    color: active ? AppPalette.accent : AppPalette.dim,
                    fontWeight: FontWeight.w700,
                    fontSize: 12,
                  ),
                ),
        ),
        const SizedBox(height: 4),
        Text(
          label,
          style: TextStyle(
            fontSize: 10,
            fontWeight: active ? FontWeight.w700 : FontWeight.w500,
            color: active ? AppPalette.text : AppPalette.dim,
          ),
        ),
      ],
    );
  }
}

// ---------------------------------------------------------------------------
// Step 0 — Welcome & guidance
// ---------------------------------------------------------------------------

class _WelcomeStep extends StatelessWidget {
  const _WelcomeStep();

  @override
  Widget build(BuildContext context) {
    return const Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        SectionHeader(title: 'Welcome to the AMR Controller'),
        SizedBox(height: 4),
        Text(
          'This client monitors and drives an AMR robot over your local network. '
          'Before you connect, make sure the robot side is ready — the app cannot '
          'fix a robot that is off, unplugged, or on another network.',
          style: TextStyle(color: AppPalette.muted, fontSize: 13, height: 1.5),
        ),
        SizedBox(height: 18),
        _GuideCard(
          title: 'On the robot (Raspberry Pi)',
          icon: Icons.memory,
          items: [
            'Power on the Pi, the Arduino and the motor battery.',
            'The Pi and this device are on the same Wi-Fi / LAN.',
            'The control server is running:  python -m amr.main --web',
            'Know the Pi\'s address — run  hostname -I  on the Pi.',
          ],
        ),
        SizedBox(height: 12),
        _GuideCard(
          title: 'On this device',
          icon: Icons.devices,
          items: [
            'Be on the same network as the robot.',
            'Have the robot\'s IP and port (default 8080) to hand.',
            'Nothing else — the next step tests the link for you.',
          ],
        ),
        SizedBox(height: 12),
        _GuideCard(
          title: 'Safety first',
          icon: Icons.health_and_safety,
          accent: AppPalette.crit,
          items: [
            'Clear the area around the robot before any motion test.',
            'Keep the physical power switch within reach.',
            'The Checks step will refuse to continue while a fatal condition '
                'is present (E-STOP, obstacle, link down).',
          ],
        ),
      ],
    );
  }
}

class _GuideCard extends StatelessWidget {
  const _GuideCard({
    required this.title,
    required this.icon,
    required this.items,
    this.accent = AppPalette.brand,
  });

  final String title;
  final IconData icon;
  final List<String> items;
  final Color accent;

  @override
  Widget build(BuildContext context) {
    return Container(
      width: double.infinity,
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
              Icon(icon, size: 16, color: accent),
              const SizedBox(width: 8),
              Text(
                title,
                style: const TextStyle(
                  fontWeight: FontWeight.w700,
                  fontSize: 13,
                  color: AppPalette.text,
                ),
              ),
            ],
          ),
          const SizedBox(height: 10),
          for (final it in items)
            Padding(
              padding: const EdgeInsets.only(bottom: 6),
              child: Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const Padding(
                    padding: EdgeInsets.only(top: 6, right: 8),
                    child: SizedBox(
                      width: 5,
                      height: 5,
                      child: DecoratedBox(
                        decoration: BoxDecoration(
                          color: AppPalette.dim,
                          shape: BoxShape.circle,
                        ),
                      ),
                    ),
                  ),
                  Expanded(
                    child: Text(
                      it,
                      style: const TextStyle(
                        color: AppPalette.muted,
                        fontSize: 12,
                        height: 1.45,
                      ),
                    ),
                  ),
                ],
              ),
            ),
        ],
      ),
    );
  }
}

// ---------------------------------------------------------------------------
// Step 1 — Connect (per-endpoint test)
// ---------------------------------------------------------------------------

class _ConnectStep extends StatelessWidget {
  const _ConnectStep({
    required this.controller,
    required this.provider,
    required this.onRun,
  });

  final TextEditingController controller;
  final RobotProvider provider;
  final Future<void> Function() onRun;

  @override
  Widget build(BuildContext context) {
    final results = provider.diagnostics;
    final coreOk = provider.coreEndpointsOk;

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const SectionHeader(title: 'Connect to the robot'),
        const SizedBox(height: 4),
        const Text(
          'Enter the robot\'s address, then run the connection test. Each part of '
          'the robot is checked separately, so a failure tells you what to fix.',
          style: TextStyle(color: AppPalette.muted, fontSize: 13, height: 1.5),
        ),
        const SizedBox(height: 16),
        TextField(
          controller: controller,
          keyboardType: TextInputType.url,
          decoration: const InputDecoration(
            labelText: 'Robot address',
            hintText: '192.168.1.42:8080',
            prefixIcon: Icon(Icons.router),
            border: OutlineInputBorder(),
          ),
          onSubmitted: (_) => onRun(),
        ),
        const SizedBox(height: 12),
        FilledButton.icon(
          onPressed: provider.diagnosticsRunning ? null : onRun,
          icon: provider.diagnosticsRunning
              ? const SpinKitThreeBounce(size: 16, color: AppPalette.onAccent)
              : const Icon(Icons.wifi_tethering),
          label: Text(provider.diagnosticsRunning
              ? 'Testing…'
              : results.isEmpty
                  ? 'Run connection test'
                  : 'Run test again'),
          style: FilledButton.styleFrom(
            padding: const EdgeInsets.symmetric(vertical: 14),
          ),
        ),
        if (results.isNotEmpty) ...[
          const SizedBox(height: 18),
          SectionHeader(
            title: 'Results',
            trailing: Text(
              coreOk ? 'robot reachable' : 'not reachable yet',
              style: TextStyle(
                fontSize: 11,
                fontWeight: FontWeight.w700,
                color: coreOk ? AppPalette.ok : AppPalette.crit,
              ),
            ),
          ),
          for (final c in results) _CheckRow(check: c),
        ],
        if (results.isEmpty && !provider.diagnosticsRunning) ...[
          const SizedBox(height: 18),
          const _Hint(
            'Tip: the robot prints its address when the server starts — look for '
            '"AMR web control: http://…".',
          ),
        ],
      ],
    );
  }
}

class _CheckRow extends StatelessWidget {
  const _CheckRow({required this.check});

  final EndpointCheck check;

  @override
  Widget build(BuildContext context) {
    final colour = check.ok
        ? AppPalette.ok
        : check.required
            ? AppPalette.crit
            : AppPalette.warn;
    final label = check.ok
        ? 'OK'
        : check.required
            ? 'FAILED'
            : 'OPTIONAL';
    return Container(
      margin: const EdgeInsets.only(bottom: 6),
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 9),
      decoration: BoxDecoration(
        color: AppPalette.surface,
        border: Border.all(color: AppPalette.line),
        borderRadius: BorderRadius.circular(8),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Icon(
                check.ok
                    ? Icons.check_circle
                    : check.required
                        ? Icons.error
                        : Icons.info_outline,
                size: 15,
                color: colour,
              ),
              const SizedBox(width: 8),
              Expanded(
                child: Text(
                  check.name,
                  style: const TextStyle(
                    fontSize: 12.5,
                    fontWeight: FontWeight.w600,
                    color: AppPalette.text,
                  ),
                ),
              ),
              if (check.latencyMs != null)
                Padding(
                  padding: const EdgeInsets.only(right: 8),
                  child: Text(
                    '${check.latencyMs} ms',
                    style: const TextStyle(color: AppPalette.dim, fontSize: 11),
                  ),
                ),
              StatusPill(label: label, colour: colour, dot: false),
            ],
          ),
          if (!check.ok) ...[
            const SizedBox(height: 6),
            Text(
              check.detail,
              style: const TextStyle(color: AppPalette.muted, fontSize: 11.5),
            ),
            if (check.fix != null)
              Padding(
                padding: const EdgeInsets.only(top: 3),
                child: Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    const Icon(Icons.build_outlined, size: 12, color: AppPalette.accent),
                    const SizedBox(width: 6),
                    Expanded(
                      child: Text(
                        check.fix!,
                        style: const TextStyle(
                          color: AppPalette.accent,
                          fontSize: 11.5,
                          height: 1.4,
                        ),
                      ),
                    ),
                  ],
                ),
              ),
          ],
        ],
      ),
    );
  }
}

// ---------------------------------------------------------------------------
// Step 2 — Checks (fatal warnings + live sensor readings)
// ---------------------------------------------------------------------------

class _ChecksStep extends StatelessWidget {
  const _ChecksStep({required this.items});

  final List<PreflightItem> items;

  @override
  Widget build(BuildContext context) {
    final p = context.watch<RobotProvider>();
    final t = p.telemetry;
    final fatal = items.where((i) => i.severity == PreflightSeverity.fatal).toList();
    final rest = items.where((i) => i.severity != PreflightSeverity.fatal).toList();

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const SectionHeader(title: 'Preflight checks'),
        const SizedBox(height: 4),
        Text(
          fatal.isEmpty
              ? 'No fatal conditions. Live sensor readings are below — confirm '
                  'they look sane before driving.'
              : 'Fix the fatal issue(s) below before driving. These block motion.',
          style: TextStyle(
            color: fatal.isEmpty ? AppPalette.muted : AppPalette.crit,
            fontSize: 13,
            height: 1.5,
            fontWeight: fatal.isEmpty ? FontWeight.w400 : FontWeight.w600,
          ),
        ),
        const SizedBox(height: 14),
        for (final item in [...fatal, ...rest]) _PreflightRow(item: item),
        const SizedBox(height: 20),
        const SectionHeader(title: 'Live sensor readings'),
        if (t == null)
          const _Hint(
            'No telemetry yet — run the connection test on the previous step.',
          )
        else
          _SensorGrid(t: t),
        if (t != null) ...[
          const SizedBox(height: 10),
          _Hint(
            'A reading of "clear" means no echo (an open path), not an obstacle. '
            'Updated ${p.lastUpdateMs == null ? '—' : 'live'} · ${t.mode ?? 'mode n/a'}',
          ),
        ],
      ],
    );
  }
}

class _PreflightRow extends StatelessWidget {
  const _PreflightRow({required this.item});

  final PreflightItem item;

  @override
  Widget build(BuildContext context) {
    final (colour, icon) = switch (item.severity) {
      PreflightSeverity.fatal => (AppPalette.crit, Icons.dangerous),
      PreflightSeverity.warning => (AppPalette.warn, Icons.warning_amber),
      PreflightSeverity.info => (AppPalette.ok, Icons.verified),
    };
    return Container(
      margin: const EdgeInsets.only(bottom: 8),
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: colour.withValues(alpha: 0.07),
        border: Border.all(color: colour.withValues(alpha: 0.5)),
        borderRadius: BorderRadius.circular(8),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Icon(icon, size: 17, color: colour),
          const SizedBox(width: 10),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  item.title,
                  style: TextStyle(
                    color: colour,
                    fontWeight: FontWeight.w800,
                    fontSize: 12.5,
                    letterSpacing: 0.3,
                  ),
                ),
                const SizedBox(height: 3),
                Text(
                  item.detail,
                  style: const TextStyle(color: AppPalette.text, fontSize: 12),
                ),
                if (item.fix != null) ...[
                  const SizedBox(height: 4),
                  Text(
                    item.fix!,
                    style: const TextStyle(
                      color: AppPalette.muted,
                      fontSize: 11.5,
                      height: 1.4,
                    ),
                  ),
                ],
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class _SensorGrid extends StatelessWidget {
  const _SensorGrid({required this.t});

  final TelemetryState t;

  /// The backend's convention: a negative reading is "no echo" (clear), and an
  /// absent one is unknown. Neither is ever rendered as a plausible number.
  String _cm(int? v) {
    if (v == null) return 'n/a';
    if (v < 0) return 'clear';
    return '$v cm';
  }

  @override
  Widget build(BuildContext context) {
    final battery = t.batteryPercentage;
    return Wrap(
      spacing: 10,
      runSpacing: 10,
      children: [
        MetricTile(
          label: 'FRONT',
          value: _cm(t.frontCm),
          icon: Icons.south,
          colour: (t.frontCm != null && t.frontCm! >= 0 && t.frontCm! < 30)
              ? AppPalette.crit
              : AppPalette.info,
        ),
        MetricTile(
          label: 'LEFT',
          value: _cm(t.leftCm),
          icon: Icons.east,
          colour: AppPalette.info,
        ),
        MetricTile(
          label: 'RIGHT',
          value: _cm(t.rightCm),
          icon: Icons.west,
          colour: AppPalette.info,
        ),
        MetricTile(
          label: 'REAR',
          value: _cm(t.rearCm),
          icon: Icons.north,
          colour: AppPalette.info,
        ),
        MetricTile(
          label: 'BATTERY',
          value: battery == null ? 'n/a' : '${battery.round()}',
          unit: battery == null ? null : '%',
          icon: Icons.battery_full,
          colour: (battery != null && battery < 20)
              ? AppPalette.crit
              : (battery != null && battery < 30)
                  ? AppPalette.warn
                  : AppPalette.ok,
        ),
        MetricTile(
          label: 'MODE',
          value: t.mode ?? 'n/a',
          icon: Icons.tune,
          colour: AppPalette.brand,
        ),
        MetricTile(
          label: 'SPEED',
          value: t.speedMps == null ? 'n/a' : t.speedMps!.toStringAsFixed(2),
          unit: 'm/s',
          icon: Icons.speed,
          colour: AppPalette.info,
        ),
        MetricTile(
          label: 'SAFETY',
          value: t.safetyAction ?? 'n/a',
          icon: Icons.health_and_safety,
          colour: t.emergencyStop ? AppPalette.crit : AppPalette.ok,
        ),
      ],
    );
  }
}

// ---------------------------------------------------------------------------
// Step 3 — Ready
// ---------------------------------------------------------------------------

class _ReadyStep extends StatelessWidget {
  const _ReadyStep({required this.provider, required this.onFinish});

  final RobotProvider provider;
  final VoidCallback onFinish;

  @override
  Widget build(BuildContext context) {
    final okCount = provider.diagnostics.where((c) => c.ok).length;
    final total = provider.diagnostics.length;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const SectionHeader(title: 'Setup complete'),
        const SizedBox(height: 8),
        Container(
          width: double.infinity,
          padding: const EdgeInsets.all(16),
          decoration: BoxDecoration(
            color: AppPalette.ok.withValues(alpha: 0.08),
            border: Border.all(color: AppPalette.ok.withValues(alpha: 0.5)),
            borderRadius: BorderRadius.circular(10),
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  const Icon(Icons.check_circle, color: AppPalette.ok),
                  const SizedBox(width: 10),
                  Expanded(
                    child: Text(
                      provider.simulation
                          ? 'Ready in simulation mode'
                          : 'Connected to ${provider.host}',
                      style: const TextStyle(
                        fontWeight: FontWeight.w700,
                        fontSize: 14,
                        color: AppPalette.text,
                      ),
                    ),
                  ),
                ],
              ),
              const SizedBox(height: 10),
              if (!provider.simulation) ...[
                KvRow(
                  label: 'endpoints',
                  value: total == 0 ? 'not tested' : '$okCount / $total responding',
                ),
                KvRow(
                  label: 'latency',
                  value: provider.latencyMs == null
                      ? 'not measured'
                      : '${provider.latencyMs} ms',
                ),
                KvRow(label: 'mode', value: provider.telemetry?.mode ?? 'n/a'),
              ],
              if (provider.simulation)
                const KvRow(
                  label: 'note',
                  value: 'commands are blocked until simulation is turned off',
                ),
            ],
          ),
        ),
        const SizedBox(height: 16),
        const _Hint(
          'You can re-run this wizard any time from Connection → "Run setup again".',
        ),
        const SizedBox(height: 20),
        FilledButton.icon(
          onPressed: onFinish,
          icon: const Icon(Icons.dashboard_customize),
          label: const Text('Open Command Center'),
          style: FilledButton.styleFrom(
            padding: const EdgeInsets.symmetric(vertical: 16),
          ),
        ),
      ],
    );
  }
}

// ---------------------------------------------------------------------------
// Shared bits
// ---------------------------------------------------------------------------

class _Hint extends StatelessWidget {
  const _Hint(this.text);
  final String text;

  @override
  Widget build(BuildContext context) {
    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const Icon(Icons.info_outline, size: 14, color: AppPalette.dim),
        const SizedBox(width: 8),
        Expanded(
          child: Text(
            text,
            style: const TextStyle(
              color: AppPalette.dim,
              fontSize: 11.5,
              height: 1.45,
            ),
          ),
        ),
      ],
    );
  }
}

class _NavBar extends StatelessWidget {
  const _NavBar({
    required this.step,
    required this.canAdvance,
    required this.onBack,
    required this.onNext,
    required this.onFinish,
  });

  final int step;
  final bool canAdvance;
  final VoidCallback? onBack;
  final VoidCallback? onNext;
  final VoidCallback onFinish;

  @override
  Widget build(BuildContext context) {
    final isLast = step == 3;
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 12),
      child: Row(
        children: [
          if (onBack != null)
            OutlinedButton.icon(
              onPressed: onBack,
              icon: const Icon(Icons.arrow_back, size: 16),
              label: const Text('Back'),
            ),
          const Spacer(),
          if (isLast)
            FilledButton.icon(
              onPressed: onFinish,
              icon: const Icon(Icons.check, size: 16),
              label: const Text('Finish'),
            )
          else
            FilledButton.icon(
              onPressed: canAdvance ? onNext : null,
              icon: const Icon(Icons.arrow_forward, size: 16),
              label: const Text('Next'),
            ),
        ],
      ),
    );
  }
}
