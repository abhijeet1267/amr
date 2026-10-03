// Connection setup — the screen an operator lands on for a device that has no
// stored or live robot connection yet, and reachable from the nav rail/tab any
// time.
//
// It owns the host/port text field, the "ping / check connection" action, the
// live Connected/Disconnected badge, and the auto-reconnect switch. All of it
// reads and writes the single RobotProvider.
library;

import 'package:flutter/material.dart';
import 'package:flutter_spinkit/flutter_spinkit.dart';
import 'package:provider/provider.dart';

import '../providers/robot_provider.dart';
import '../theme/theme.dart';

class ConnectionScreen extends StatefulWidget {
  const ConnectionScreen({super.key});

  @override
  State<ConnectionScreen> createState() => _ConnectionScreenState();
}

class _ConnectionScreenState extends State<ConnectionScreen> {
  late final TextEditingController _controller;
  RobotProvider? _provider;

  @override
  void initState() {
    super.initState();
    // Capture the provider once: `context.read` is not safe in `dispose` (the
    // inherited widget may already be unmounted), so we hold our own reference
    // and drop the listener with it.
    _provider = context.read<RobotProvider>();
    _controller = TextEditingController(text: _provider!.host);
    // The saved host loads asynchronously; if it arrives after this widget is
    // built (and the operator has not typed anything), seed the field with it.
    _provider!.addListener(_onProviderChanged);
  }

  void _onProviderChanged() {
    final provider = _provider;
    if (!mounted || provider == null || _controller.text.isNotEmpty) return;
    if (provider.host.isNotEmpty) {
      _controller.text = provider.host;
      _controller.selection =
          TextSelection.collapsed(offset: _controller.text.length);
    }
  }

  @override
  void dispose() {
    _provider?.removeListener(_onProviderChanged);
    _controller.dispose();
    super.dispose();
  }

  Future<void> _ping() async {
    final provider = context.read<RobotProvider>();
    provider.saveHost(_controller.text);
    await provider.ping();
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content: Text(
          provider.isConnected
              ? 'Connected to ${provider.host}'
              : 'Connection failed: ${provider.connectionDetail}',
        ),
        backgroundColor:
            provider.isConnected ? AppPalette.ok : AppPalette.crit,
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final provider = context.watch<RobotProvider>();

    return Scaffold(
      appBar: AppBar(title: const Text('Connection')),
      body: Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 520),
          child: SingleChildScrollView(
            padding: const EdgeInsets.all(24),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                _ConnectionBadge(state: provider.connection),
                const SizedBox(height: 24),
                TextField(
                  controller: _controller,
                  keyboardType: TextInputType.url,
                  decoration: const InputDecoration(
                    labelText: 'Robot address',
                    hintText: '192.168.1.100:8080',
                    prefixIcon: Icon(Icons.router),
                    border: OutlineInputBorder(),
                  ),
                  onSubmitted: (_) => _ping(),
                ),
                const SizedBox(height: 16),
                SwitchListTile(
                  title: const Text('Auto-reconnect'),
                  subtitle: const Text(
                    'Re-probe the robot automatically if the link drops',
                  ),
                  value: provider.autoReconnect,
                  onChanged: (v) => context.read<RobotProvider>().setAutoReconnect(v),
                ),
                const SizedBox(height: 16),
                FilledButton.icon(
                  onPressed: provider.busy ? null : _ping,
                  icon: provider.busy
                      ? const SpinKitThreeBounce(size: 18, color: AppPalette.onAccent)
                      : const Icon(Icons.wifi_tethering),
                  label: Text(
                    provider.busy
                        ? 'Checking…'
                        : provider.isConnected
                            ? 'Re-check connection'
                            : 'Ping / check connection',
                  ),
                  style: FilledButton.styleFrom(
                    padding: const EdgeInsets.symmetric(vertical: 16),
                  ),
                ),
                const SizedBox(height: 24),
                Text(
                  provider.connectionDetail.isEmpty
                      ? 'Enter the robot’s host and port, then ping to connect.'
                      : provider.connectionDetail,
                  textAlign: TextAlign.center,
                  style: TextStyle(
                    color: provider.connection == ConnectionState.error
                        ? AppPalette.crit
                        : AppPalette.muted,
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

class _ConnectionBadge extends StatelessWidget {
  const _ConnectionBadge({required this.state});

  final ConnectionState state;

  @override
  Widget build(BuildContext context) {
    final (color, icon, label) = switch (state) {
      ConnectionState.connected => (AppPalette.ok, Icons.check_circle, 'Connected'),
      ConnectionState.connecting => (AppPalette.info, Icons.sync, 'Connecting…'),
      ConnectionState.error => (AppPalette.crit, Icons.error_outline, 'Disconnected'),
      ConnectionState.disconnected => (AppPalette.muted, Icons.circle_outlined, 'Disconnected'),
    };

    return Container(
      padding: const EdgeInsets.symmetric(vertical: 12, horizontal: 16),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.12),
        border: Border.all(color: color),
        borderRadius: BorderRadius.circular(10),
      ),
      child: Row(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          Icon(icon, color: color),
          const SizedBox(width: 10),
          Text(
            label,
            style: TextStyle(
              color: color,
              fontWeight: FontWeight.w600,
              letterSpacing: 0.5,
            ),
          ),
        ],
      ),
    );
  }
}