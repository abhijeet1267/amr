// The visual identity of the AMR client.
//
// Direction: a *classic, premium brass-instrument* palette, not a cold black +
// blue terminal. Surfaces are warm charcoal/espresso rather than blue-black;
// the primary accent is brass gold (the classic proof/brand colour of a control
// station); status stays emerald/amber/ruby; and a muted steel-blue survives
// only as the secondary "technical/info" voice so the palette is not one-note.
//
// Colour is never the only signal: every status also prints its text.

import 'package:flutter/material.dart';

abstract final class AppPalette {
  // Surfaces — warm charcoal ramp (espresso, not blue-black).
  static const Color background = Color(0xFF14100B);
  static const Color surface = Color(0xFF1E1812);
  static const Color surfaceVariant = Color(0xFF262019);
  static const Color line = Color(0xFF3C3224);
  static const Color text = Color(0xFFF3ECDD);
  static const Color muted = Color(0xFFA89981);
  static const Color dim = Color(0xFF776C57);

  // The electric brass primary accent — classic instrument gold.
  static const Color accent = Color(0xFFD9A23B);
  static const Color onAccent = Color(0xFF231A08);

  // Status four — emerald / amber / ruby / muted steel-blue.
  static const Color ok = Color(0xFF3CB47D);
  static const Color warn = Color(0xFFE0A23D);
  static const Color crit = Color(0xFFE2544E);
  static const Color info = Color(0xFF5A8CC4);

  // Brass reserved for "proof / brand" emphasis (a touch richer than accent).
  static const Color gold = Color(0xFFE0B354);
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