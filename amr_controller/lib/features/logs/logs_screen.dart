// Event & Command Log — a live, filterable operator log.
//
// Entries come from the provider's EventLog, which the real connection/command
// paths already write to (connect, mode changes, motion commands, E-STOP,
// refusals). Safety entries stay visible until acknowledged (cleared here).

import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../core/event_log.dart';
import '../../providers/robot_provider.dart';
import '../../theme/theme.dart';
import '../../widgets/status_widgets.dart';

class LogsScreen extends StatefulWidget {
  const LogsScreen({super.key});

  @override
  State<LogsScreen> createState() => _LogsScreenState();
}

class _LogsScreenState extends State<LogsScreen> {
  LogLevel? _filter;
  String _query = '';

  @override
  Widget build(BuildContext context) {
    final log = context.watch<RobotProvider>().eventLog;

    final entries = log.entries.where((e) {
      if (_filter != null && e.level != _filter) return false;
      if (_query.isNotEmpty && !e.message.toLowerCase().contains(_query.toLowerCase())) {
        return false;
      }
      return true;
    }).toList().reversed.toList();

    return Column(
      children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(20, 16, 20, 8),
          child: Row(
            children: [
              const Expanded(child: SectionHeader(title: 'Event & Command Log')),
              IconButton(
                icon: const Icon(Icons.file_download, size: 18),
                tooltip: 'Export log (console)',
                onPressed: () => _export(log),
              ),
              IconButton(
                icon: const Icon(Icons.delete_outline, size: 18),
                tooltip: 'Clear display',
                onPressed: () => log.clear(),
              ),
            ],
          ),
        ),
        Padding(
          padding: const EdgeInsets.symmetric(horizontal: 20),
          child: Column(
            children: [
              TextField(
                decoration: const InputDecoration(
                  hintText: 'Search messages…',
                  prefixIcon: Icon(Icons.search, size: 18),
                  isDense: true,
                  border: OutlineInputBorder(),
                ),
                onChanged: (v) => setState(() => _query = v),
              ),
              const SizedBox(height: 8),
              Wrap(
                spacing: 6,
                children: [
                  for (final lvl in LogLevel.values)
                    FilterChip(
                      label: Text(lvl.label),
                      selected: _filter == lvl,
                      onSelected: (sel) => setState(() => _filter = sel ? lvl : null),
                    ),
                ],
              ),
            ],
          ),
        ),
        const SizedBox(height: 8),
        Expanded(
          child: entries.isEmpty
              ? const Center(
                  child: Text('No events yet', style: TextStyle(color: AppPalette.dim)),
                )
              : ListView.builder(
                  padding: const EdgeInsets.symmetric(horizontal: 20),
                  itemCount: entries.length,
                  itemBuilder: (context, i) => _LogRow(entry: entries[i]),
                ),
        ),
      ],
    );
  }

  void _export(EventLog log) {
    // Console export is an operator convenience; Flutter has no file-picker by
    // default. Structured, so a follow-up can switch to share/file without
    // changing the data.
    debugPrint('--- AMR event log export ---');
    for (final e in log.entries) {
      debugPrint('${e.hhmmss} ${e.level.label.padRight(6)} ${e.message}');
    }
    ScaffoldMessenger.of(context).showSnackBar(
      const SnackBar(content: Text('Log exported to console')),
    );
  }
}

class _LogRow extends StatelessWidget {
  const _LogRow({required this.entry});

  final LogEntry entry;

  Color get _colour => switch (entry.level) {
        LogLevel.info => AppPalette.info,
        LogLevel.command => AppPalette.accent,
        LogLevel.warning => AppPalette.warn,
        LogLevel.safety => AppPalette.crit,
        LogLevel.error => AppPalette.crit,
      };

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 3),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SizedBox(
            width: 60,
            child: Text(
              entry.hhmmss,
              style: const TextStyle(color: AppPalette.dim, fontSize: 12),
            ),
          ),
          SizedBox(
            width: 60,
            child: Text(
              entry.level.label,
              style: TextStyle(color: _colour, fontSize: 12, fontWeight: FontWeight.w700),
            ),
          ),
          Expanded(
            child: Text(
              entry.message,
              style: const TextStyle(color: AppPalette.text, fontSize: 12),
            ),
          ),
        ],
      ),
    );
  }
}