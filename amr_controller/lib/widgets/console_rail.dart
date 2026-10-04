// A scrollable desktop navigation rail. Replaces NavigationRail, which does
// not scroll on its own and overflows with a large destination set on short
// viewports. This is a plain ListView of buttons: bounded, scrollable, and
// styled to the console theme.

import 'package:flutter/material.dart';

import '../theme/theme.dart';

class ConsoleRail extends StatelessWidget {
  const ConsoleRail({
    super.key,
    required this.index,
    required this.onSelect,
    required this.items,
  });

  final int index;
  final void Function(int) onSelect;
  final List<(IconData, IconData, String)> items;

  @override
  Widget build(BuildContext context) {
    return Container(
      width: 88,
      color: AppPalette.surface,
      child: ListView.builder(
        padding: const EdgeInsets.symmetric(vertical: 8),
        itemCount: items.length,
        itemBuilder: (context, i) {
          final (icon, iconSel, label) = items[i];
          final selected = i == index;
          return Tooltip(
            message: label,
            child: InkWell(
              onTap: () => onSelect(i),
              child: Container(
                margin: const EdgeInsets.symmetric(horizontal: 6, vertical: 3),
                padding: const EdgeInsets.symmetric(vertical: 10),
                decoration: BoxDecoration(
                  color: selected ? AppPalette.accent.withValues(alpha: 0.16) : null,
                  border: Border.all(
                    color: selected ? AppPalette.accent : Colors.transparent,
                  ),
                  borderRadius: BorderRadius.circular(8),
                ),
                child: Column(
                  children: [
                    Icon(
                      selected ? iconSel : icon,
                      size: 20,
                      color: selected ? AppPalette.accent : AppPalette.muted,
                    ),
                    const SizedBox(height: 4),
                    Text(
                      label,
                      textAlign: TextAlign.center,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: TextStyle(
                        fontSize: 10,
                        color: selected ? AppPalette.accent : AppPalette.muted,
                      ),
                    ),
                  ],
                ),
              ),
            ),
          );
        },
      ),
    );
  }
}