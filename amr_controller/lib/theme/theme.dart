// The visual identity of the AMR client.
//
// Direction: a *light industrial control* palette — white panels on a pale
// neutral canvas, hairline separators, and a single restrained engineering
// blue as the primary accent. Status keeps the emerald / amber / ruby /
// steel-blue quartet, darkened to hold contrast on white. There is no
// decorative colour: blue selects and informs, and the status quartet only
// ever reports machine state.
//
// Colour is never the only signal: every status also prints its text.

import 'package:flutter/material.dart';

abstract final class AppPalette {
  // Surfaces — pale neutral canvas, white working panels, faint tile fill.
  static const Color background = Color(0xFFF3F5F7);
  static const Color surface = Color(0xFFFFFFFF);
  static const Color surfaceVariant = Color(0xFFEDF0F3);
  static const Color line = Color(0xFFD8DEE5);

  // Text — near-black primary, two muted steps for secondary and metadata.
  static const Color text = Color(0xFF182026);
  static const Color muted = Color(0xFF51606E);
  static const Color dim = Color(0xFF8592A0);

  // Primary accent — restrained engineering blue (selects, informs, navigates).
  static const Color accent = Color(0xFF1A5FB4);
  static const Color onAccent = Color(0xFFFFFFFF);

  // Status four — emerald / amber / ruby / steel-blue, tuned for white
  // surfaces (every value holds ~4.5:1 against the panel colour).
  static const Color ok = Color(0xFF1E7F4F);
  static const Color warn = Color(0xFF9A6700);
  static const Color crit = Color(0xFFC0392B);
  static const Color info = Color(0xFF3B6EA5);

  // Brand emphasis — the accent's deeper voice, used for the section bar and
  // "proof" markers. (Formerly `gold` in the dark theme.)
  static const Color brand = Color(0xFF15497F);
}

ThemeData buildAppTheme() {
  final base = ThemeData(
    brightness: Brightness.light,
    useMaterial3: true,
    // Roboto is bundled in `assets/fonts/` (see pubspec.yaml). Naming it here
    // makes Flutter web use the local font instead of downloading it from
    // Google Fonts at runtime — which is what leaves a blank, text-less UI on
    // a network where Google is blocked.
    fontFamily: 'Roboto',
    colorScheme: const ColorScheme.light(
      primary: AppPalette.accent,
      onPrimary: AppPalette.onAccent,
      secondary: AppPalette.brand,
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
      indicatorColor: Color(0x1F1A5FB4),
      labelTextStyle: WidgetStatePropertyAll(
        TextStyle(color: AppPalette.muted, fontSize: 12),
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
