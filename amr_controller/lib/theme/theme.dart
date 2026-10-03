// The visual identity of the AMR client.
//
// This palette is *not* invented for the app. It mirrors the robot's own
// Command Center tokens (raspberry_pi/amr/web/static/command_center.css) value
// for value, for the same reason the repo's web surfaces share one palette: an
// operator who reads the console on the Pi and then opens this client should
// not see a different product. Use AppTheme.statusColour / AppTheme.accent, not
// raw hexes, everywhere below the theme layer.
library;

import 'package:flutter/material.dart';

abstract final class AppPalette {
  // Surfaces — the console's slate ramp.
  static const Color background = Color(0xFF0B0F16);
  static const Color surface = Color(0xFF141D2B);
  static const Color surfaceVariant = Color(0xFF1A2534);
  static const Color line = Color(0xFF24334A);
  static const Color text = Color(0xFFE6EDF7);
  static const Color muted = Color(0xFF8FA3BD);
  static const Color dim = Color(0xFF64768C);

  // The electric accent — the console's --accent (#22d3ee).
  static const Color accent = Color(0xFF22D3EE);
  static const Color onAccent = Color(0xFF04121A);

  // Status four — the console's --ok/--warn/--crit/--info. Colour is never the
  // only signal: every status is also printed as text.
  static const Color ok = Color(0xFF2FBF71);
  static const Color warn = Color(0xFFE8A33D);
  static const Color crit = Color(0xFFEF4D5A);
  static const Color info = Color(0xFF3D8BFD);

  // Brass — the console's --gold (proof / brand).
  static const Color gold = Color(0xFFDCB35D);
}

ThemeData buildAppTheme() {
  final base = ThemeData(
    brightness: Brightness.dark,
    useMaterial3: true,
    colorScheme: const ColorScheme.dark(
      primary: AppPalette.accent,
      onPrimary: AppPalette.onAccent,
      secondary: AppPalette.gold,
      surface: AppPalette.surface,
      error: AppPalette.crit,
      onSurface: AppPalette.text,
      outline: AppPalette.line,
    ),
    scaffoldBackgroundColor: AppPalette.background,
    cardColor: AppPalette.surface,
  );

  return base.copyWith(
    textTheme: base.textTheme.apply(
      bodyColor: AppPalette.text,
      displayColor: AppPalette.text,
    ),
    appBarTheme: const AppBarTheme(
      backgroundColor: AppPalette.surface,
      foregroundColor: AppPalette.text,
      elevation: 0,
    ),
    navigationRailTheme: const NavigationRailThemeData(
      backgroundColor: AppPalette.surface,
      indicatorColor: AppPalette.accent,
      selectedIconTheme: IconThemeData(color: AppPalette.onAccent),
      selectedLabelTextStyle: TextStyle(color: AppPalette.accent),
      unselectedIconTheme: IconThemeData(color: AppPalette.muted),
      unselectedLabelTextStyle: TextStyle(color: AppPalette.muted),
    ),
    navigationBarTheme: const NavigationBarThemeData(
      backgroundColor: AppPalette.surface,
      indicatorColor: AppPalette.accent,
      labelTextStyle: WidgetStatePropertyAll(
        TextStyle(color: AppPalette.text, fontSize: 12),
      ),
    ),
    dividerTheme: const DividerThemeData(color: AppPalette.line),
  );
}

/// Maps an AMR status string to a colour *and* keeps the text itself visible,
/// because colour is never the only signal in this product.
Color statusColour(String status) {
  switch (status.trim().toUpperCase()) {
    case 'AVAILABLE':
      return AppPalette.ok;
    case 'OFFLINE':
    case 'CRITICAL':
    case 'ERROR':
    case 'FAULT':
    case 'UNAVAILABLE':
    case 'NOT_AVAILABLE':
      return AppPalette.crit;
    case 'WARNING':
    case 'MOCK':
    case 'PARTIAL':
    case 'HARDWARE REQUIRED':
    case 'BUILD NOT AVAILABLE':
    case 'NOT INSTALLED':
    case 'DEVELOPMENT':
    case 'COMING SOON':
    case 'NOT TESTED':
    case 'HARDWARE_REQUIRED':
    case 'NOT_INSTALLED':
    case 'BUILD_NOT_AVAILABLE':
      return AppPalette.warn;
    default:
      return AppPalette.info;
  }
}