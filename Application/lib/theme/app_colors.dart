import 'package:flutter/material.dart';

/// RunSense's color system. Two roles:
///  - `Light`/`Dark` — the brand palette (bg/surface/ink/muted/primary/accent),
///    fed into AppTheme's ColorScheme.
///  - The semantic alert-tier and guide-status colors below, which are
///    deliberately theme-invariant: they're always drawn as large full-bleed
///    fills with white text/icons on top (Live Run's zone panel, Week Plan's
///    GuideStatusChip), so they don't need a separate light/dark variant.
///
/// Tiers escalate cool -> warm (notice=teal, warning=amber, danger=red)
/// rather than amber->orange->red — cool-for-calm/warm-for-alarm reads
/// faster at a glance than three warm hues that only differ in saturation,
/// and echoes the blue-info/amber-caution/red-stop convention from safety
/// signage.
abstract class AppColorsLight {
  static const bg = Color(0xFFFFFFFF);
  static const surface = Color(0xFFF3F4FA);
  static const surfaceAlt = Color(0xFFE3E5F0);
  static const ink = Color(0xFF14162B);
  static const muted = Color(0xFF5B5F78);
  static const primary = Color(0xFF33409E);
  static const onPrimary = Color(0xFFFFFFFF);
  static const accent = Color(0xFF0E90A6);
  static const onAccent = Color(0xFFFFFFFF);
}

abstract class AppColorsDark {
  static const bg = Color(0xFF0B0B10);
  static const surface = Color(0xFF15161F);
  static const surfaceAlt = Color(0xFF262837);
  static const ink = Color(0xFFF1F1F8);
  static const muted = Color(0xFF9A9DB8);
  static const primary = Color(0xFF5C68D4);
  static const onPrimary = Color(0xFFFFFFFF);
  static const accent = Color(0xFF37C6DA);
  static const onAccent = Color(0xFF0B0B10);
}

/// Alert tiers (Live Run) and guide status (Week Plan) — one shared
/// semantic vocabulary, same colors used for both (accepted/danger both
/// read as "the bad/urgent one" etc.), so the app has a single consistent
/// meaning per hue instead of two unrelated color systems.
abstract class AppSemanticColors {
  static const notice = Color(0xFF0E7C91);
  static const warning = Color(0xFFB2540A);
  static const danger = Color(0xFFC42B2B);
  static const idle = Color(0xFF454864);
  static const accepted = Color(0xFF1F8A55);
  static const neutral = Color(0xFF5B5F78);
  static const onFill = Color(0xFFFFFFFF);
}
