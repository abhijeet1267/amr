// Applications Hub — the 24 interface cards from GET /applications/state,
// grouped by category, each with a status chip and a quick action.
//
// Every card's status is the robot's verbatim verdict; this screen never
// upgrades or invents one. Colour is decoration: the status text is always
// printed. The registry is a directory describing *other* interfaces, so a
// card's action only opens a browser at the robot's URL when one exists; an
// entry with no `url` is honestly labelled "API — no interface".
library;

import 'package:flutter/material.dart';
import 'package:flutter_spinkit/flutter_spinkit.dart';
import 'package:provider/provider.dart';
import 'package:url_launcher/url_launcher.dart';

import '../models/app_state.dart';
import '../providers/robot_provider.dart';
import '../theme/theme.dart';
import '../widgets/app_card.dart';
import 'connection_screen.dart';

class ApplicationsHubScreen extends StatelessWidget {
  const ApplicationsHubScreen({super.key});

  @override
  Widget build(BuildContext context) {
    final provider = context.watch<RobotProvider>();

    if (!provider.isConnected) {
      return const _NotConnected();
    }

    final registry = provider.registry;
    if (registry == null) {
      return const Center(
        child: SpinKitThreeBounce(color: AppPalette.accent, size: 24),
      );
    }

    if (registry.applications.isEmpty) {
      return const Center(
        child: Text(
          'The robot reported no applications.',
          style: TextStyle(color: AppPalette.muted),
        ),
      );
    }

    return Scaffold(
      appBar: AppBar(
        title: const Text('Applications Hub'),
        actions: [
          _StatusBand(count: registry.count ?? registry.applications.length),
          const SizedBox(width: 12),
        ],
      ),
      body: RefreshIndicator(
        onRefresh: () async {
          await context.read<RobotProvider>().ping();
        },
        child: ListView(
          padding: const EdgeInsets.all(16),
          children: [
            for (final category in registry.categories) ...[
              _CategoryHeader(
                category: category,
                count: registry.applications
                    .where((a) => a.category == category)
                    .length,
              ),
              const SizedBox(height: 8),
              GridView.builder(
                shrinkWrap: true,
                physics: const NeverScrollableScrollPhysics(),
                gridDelegate: const SliverGridDelegateWithMaxCrossAxisExtent(
                  maxCrossAxisExtent: 420,
                  mainAxisExtent: 210,
                  crossAxisSpacing: 12,
                  mainAxisSpacing: 12,
                ),
                itemCount: registry.applications
                    .where((a) => a.category == category)
                    .length,
                itemBuilder: (context, i) {
                  final apps =
                      registry.applications.where((a) => a.category == category).toList();
                  return AppCard(
                    app: apps[i],
                    onOpen: () => _openApp(context, apps[i]),
                  );
                },
              ),
              const SizedBox(height: 24),
            ],
          ],
        ),
      ),
    );
  }

  Future<void> _openApp(BuildContext context, AppState app) async {
    final provider = context.read<RobotProvider>();
    final url = app.url ?? '';
    if (url.isEmpty) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('API — no interface to open.')),
      );
      return;
    }
    // Map a server-relative route (/command-center) onto the robot origin.
    final target = url.startsWith('http')
        ? url
        : '${provider.origin}$url';
    final uri = Uri.parse(target);
    final ok = await launchUrl(uri, mode: LaunchMode.externalApplication);
    if (!ok && context.mounted) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('Could not open $target')),
      );
    }
  }
}

class _NotConnected extends StatelessWidget {
  const _NotConnected();

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Applications Hub')),
      body: Center(
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            const Icon(Icons.wifi_off, size: 48, color: AppPalette.muted),
            const SizedBox(height: 16),
            const Text(
              'Not connected',
              style: TextStyle(fontSize: 18, color: AppPalette.text),
            ),
            const SizedBox(height: 8),
            const Text(
              'Connect from the Connection screen to load the hub.',
              style: TextStyle(color: AppPalette.muted),
            ),
            const SizedBox(height: 16),
            FilledButton.icon(
              onPressed: () => Navigator.of(context).push(
                MaterialPageRoute(builder: (_) => const ConnectionScreen()),
              ),
              icon: const Icon(Icons.settings_input_component),
              label: const Text('Open Connection'),
            ),
          ],
        ),
      ),
    );
  }
}

class _StatusBand extends StatelessWidget {
  const _StatusBand({required this.count});
  final int count;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(top: 8),
      child: Chip(
        label: Text('$count interfaces'),
        avatar: const Icon(Icons.apps, size: 16, color: AppPalette.accent),
        backgroundColor: AppPalette.surfaceVariant,
      ),
    );
  }
}

class _CategoryHeader extends StatelessWidget {
  const _CategoryHeader({required this.category, required this.count});
  final String category;
  final int count;

  @override
  Widget build(BuildContext context) {
    final title = category.isEmpty
        ? 'Other'
        : '${category[0].toUpperCase()}${category.substring(1)}';
    return Row(
      children: [
        const SizedBox(width: 4, height: 16),
        Container(width: 3, height: 16, color: AppPalette.gold),
        const SizedBox(width: 10),
        Text(
          title,
          style: const TextStyle(
            fontWeight: FontWeight.w600,
            fontSize: 15,
            color: AppPalette.text,
          ),
        ),
        const SizedBox(width: 8),
        Text(
          '$count',
          style: const TextStyle(color: AppPalette.dim, fontSize: 12),
        ),
      ],
    );
  }
}