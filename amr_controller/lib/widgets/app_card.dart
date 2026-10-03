// A single card in the Applications Hub.
//
// Shows the title, the status (as a coloured chip *and* the verbatim text),
// the description, and a quick action. The action is "Open" for anything with
// a URL and deliberately "API — no interface" for an endpoint entry, because a
// card that links nowhere-but-looks-clickable is the thing this directory
// exists to prevent.
library;

import 'package:flutter/material.dart';

import '../models/app_state.dart';
import '../theme/theme.dart';

class AppCard extends StatelessWidget {
  const AppCard({super.key, required this.app, required this.onOpen});

  final AppState app;
  final VoidCallback onOpen;

  @override
  Widget build(BuildContext context) {
    final accent = statusColour(app.status);

    return Container(
      decoration: BoxDecoration(
        color: AppPalette.surface,
        border: Border.all(color: AppPalette.line),
        borderRadius: BorderRadius.circular(10),
        boxShadow: const [
          BoxShadow(color: Color(0x14000000), blurRadius: 6, offset: Offset(0, 2)),
        ],
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          // Left accent bar + title + status chip.
          Row(
            children: [
              Container(width: 3, height: 40, color: accent),
              const SizedBox(width: 12),
              Expanded(
                child: Text(
                  app.name,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: const TextStyle(
                    fontWeight: FontWeight.w600,
                    fontSize: 15,
                    color: AppPalette.text,
                  ),
                ),
              ),
              Padding(
                padding: const EdgeInsets.only(right: 10),
                child: _StatusChip(status: app.status, colour: accent),
              ),
            ],
          ),
          const SizedBox(height: 8),
          Expanded(
            child: Padding(
              padding: const EdgeInsets.symmetric(horizontal: 12),
              child: Text(
                app.detail ?? app.description,
                maxLines: 4,
                overflow: TextOverflow.ellipsis,
                style: const TextStyle(
                  color: AppPalette.muted,
                  fontSize: 12.5,
                  height: 1.4,
                ),
              ),
            ),
          ),
          const Divider(height: 1),
          Padding(
            padding: const EdgeInsets.fromLTRB(12, 8, 12, 10),
            child: Row(
              children: [
                // Matches the web hub exactly: "can command motion" is the
                // cautionary (amber) flag; "read-only" is the neutral one.
                if (app.readOnly)
                  const _Flag(label: 'read-only', colour: AppPalette.muted)
                else
                  const _Flag(label: 'can command', colour: AppPalette.warn),
                const SizedBox(width: 6),
                if (app.requiresRobot) const _Flag(label: 'needs robot', colour: AppPalette.muted),
                if (app.requiresHardware) const _Flag(label: 'needs hardware', colour: AppPalette.muted),
                const Spacer(),
                app.hasInterface
                    ? TextButton.icon(
                        onPressed: onOpen,
                        icon: const Icon(Icons.open_in_new, size: 16, color: AppPalette.accent),
                        label: const Text('Open'),
                        style: TextButton.styleFrom(
                          foregroundColor: AppPalette.accent,
                        ),
                      )
                    : const Text(
                        'API — no interface',
                        style: TextStyle(
                          color: AppPalette.dim,
                          fontStyle: FontStyle.italic,
                          fontSize: 11,
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

class _StatusChip extends StatelessWidget {
  const _StatusChip({required this.status, required this.colour});
  final String status;
  final Color colour;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
      decoration: BoxDecoration(
        color: colour.withValues(alpha: 0.12),
        borderRadius: BorderRadius.circular(999),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Container(width: 7, height: 7, decoration: BoxDecoration(color: colour, shape: BoxShape.circle)),
          const SizedBox(width: 5),
          Text(
            status,
            style: TextStyle(color: colour, fontSize: 10, fontWeight: FontWeight.w600),
          ),
        ],
      ),
    );
  }
}

class _Flag extends StatelessWidget {
  const _Flag({required this.label, required this.colour});
  final String label;
  final Color colour;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 5, vertical: 2),
      decoration: BoxDecoration(
        border: Border.all(color: colour.withValues(alpha: 0.5)),
        borderRadius: BorderRadius.circular(4),
      ),
      child: Text(
        label,
        style: TextStyle(color: colour, fontSize: 9, fontWeight: FontWeight.w600),
      ),
    );
  }
}