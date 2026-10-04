// Formatting helpers shared across the operator UI.
//
// Every value is a *display concern*; nothing here fabricates data. Unknown
// values are formatted as "—" / "no sensor", never as a plausible number.

library;

String fmtDuration(Duration d) {
  final h = d.inHours;
  final m = d.inMinutes.remainder(60);
  final s = d.inSeconds.remainder(60);
  if (h > 0) return '$h h $m m';
  if (m > 0) return '$m m $s s';
  return '$s s';
}

String fmtMmss(Duration d) {
  final m = d.inMinutes.remainder(60).toString().padLeft(2, '0');
  final s = d.inSeconds.remainder(60).toString().padLeft(2, '0');
  return '$m:$s';
}

/// A decimal with one place and a unit, or a clear unknown marker.
String fmtOrDash(num? v, String unit, {int digits = 1}) {
  if (v == null) return '—';
  return '${v.toStringAsFixed(digits)} $unit';
}

String fmtIntOrDash(num? v, String unit) {
  if (v == null) return '—';
  return '${v.round()} $unit';
}

/// Milliseconds as "24 ms" or a clear unknown marker.
String fmtLatency(int? ms) {
  if (ms == null) return '—';
  return '$ms ms';
}

/// Timestamp (ms since epoch) as HH:mm:ss local; null → "—".
String fmtClock(int? epochMs) {
  if (epochMs == null) return '—';
  final t = DateTime.fromMillisecondsSinceEpoch(epochMs);
  return '${t.hour.toString().padLeft(2, '0')}:'
      '${t.minute.toString().padLeft(2, '0')}:'
      '${t.second.toString().padLeft(2, '0')}';
}