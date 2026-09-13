import 'package:flutter/material.dart';

import 'app_colors.dart';

/// RunSense's light/dark ThemeData. Builds an explicit ColorScheme instead
/// of a bare `ColorScheme.fromSeed` (the stock Material-you look every
/// unstyled Flutter app defaults to) — the roles that are actually visible
/// (primary, secondary, surface, on-surface, error) are pinned to
/// AppColors; fromSeed only fills in the tonal roles nothing here uses.
abstract class AppTheme {
  static ThemeData get light => _build(Brightness.light);
  static ThemeData get dark => _build(Brightness.dark);

  static ThemeData _build(Brightness brightness) {
    final isDark = brightness == Brightness.dark;
    final bg = isDark ? AppColorsDark.bg : AppColorsLight.bg;
    final surface = isDark ? AppColorsDark.surface : AppColorsLight.surface;
    final surfaceAlt = isDark ? AppColorsDark.surfaceAlt : AppColorsLight.surfaceAlt;
    final ink = isDark ? AppColorsDark.ink : AppColorsLight.ink;
    final muted = isDark ? AppColorsDark.muted : AppColorsLight.muted;
    final primary = isDark ? AppColorsDark.primary : AppColorsLight.primary;
    final onPrimary = isDark ? AppColorsDark.onPrimary : AppColorsLight.onPrimary;
    final accent = isDark ? AppColorsDark.accent : AppColorsLight.accent;
    final onAccent = isDark ? AppColorsDark.onAccent : AppColorsLight.onAccent;

    final colorScheme = ColorScheme.fromSeed(
      seedColor: primary,
      brightness: brightness,
    ).copyWith(
      primary: primary,
      onPrimary: onPrimary,
      secondary: accent,
      onSecondary: onAccent,
      surface: bg,
      onSurface: ink,
      error: AppSemanticColors.danger,
      onError: AppSemanticColors.onFill,
    );

    final baseTextTheme =
        isDark ? Typography.whiteMountainView : Typography.blackMountainView;
    final textTheme = baseTextTheme.copyWith(
      headlineSmall: baseTextTheme.headlineSmall?.copyWith(
        color: ink,
        fontWeight: FontWeight.w700,
        letterSpacing: -0.2,
        height: 1.25,
      ),
      titleLarge: baseTextTheme.titleLarge?.copyWith(
        color: ink,
        fontWeight: FontWeight.w700,
      ),
      titleMedium: baseTextTheme.titleMedium?.copyWith(
        color: ink,
        fontWeight: FontWeight.w600,
      ),
      bodyLarge: baseTextTheme.bodyLarge?.copyWith(color: ink, height: 1.35),
      bodyMedium: baseTextTheme.bodyMedium?.copyWith(color: muted, height: 1.35),
      bodySmall: baseTextTheme.bodySmall?.copyWith(color: muted),
    );

    return ThemeData(
      useMaterial3: true,
      brightness: brightness,
      scaffoldBackgroundColor: bg,
      colorScheme: colorScheme,
      textTheme: textTheme,
      dividerColor: surfaceAlt,
      splashFactory: InkRipple.splashFactory,
      appBarTheme: AppBarTheme(
        backgroundColor: bg,
        foregroundColor: ink,
        elevation: 0,
        scrolledUnderElevation: 0,
        surfaceTintColor: Colors.transparent,
        titleTextStyle: textTheme.titleLarge,
        iconTheme: IconThemeData(color: ink),
      ),
      elevatedButtonTheme: ElevatedButtonThemeData(
        style: ElevatedButton.styleFrom(
          backgroundColor: primary,
          foregroundColor: onPrimary,
          disabledBackgroundColor: surfaceAlt,
          disabledForegroundColor: muted,
          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
          elevation: 0,
        ),
      ),
      outlinedButtonTheme: OutlinedButtonThemeData(
        style: OutlinedButton.styleFrom(
          foregroundColor: primary,
          disabledForegroundColor: muted,
          side: BorderSide(color: primary, width: 1.5),
          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
        ).copyWith(
          side: WidgetStateProperty.resolveWith((states) {
            final color = states.contains(WidgetState.disabled) ? surfaceAlt : primary;
            return BorderSide(color: color, width: 1.5);
          }),
        ),
      ),
      iconButtonTheme: IconButtonThemeData(
        style: IconButton.styleFrom(foregroundColor: ink),
      ),
      chipTheme: const ChipThemeData(
        labelStyle: TextStyle(color: Colors.white, fontWeight: FontWeight.w600),
        side: BorderSide.none,
      ),
      snackBarTheme: SnackBarThemeData(
        backgroundColor: ink,
        contentTextStyle: TextStyle(color: bg),
        behavior: SnackBarBehavior.floating,
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
      ),
      progressIndicatorTheme: ProgressIndicatorThemeData(color: primary),
      // Not read directly by ColorScheme, but screens reach for a subtle
      // panel/divider tone via Theme.of(context).extension<_Surfaces>() so
      // "surface"/"surfaceAlt" stay named concepts instead of ad hoc grays.
      extensions: [_Surfaces(panel: surface, border: surfaceAlt)],
    );
  }
}

/// Small ThemeExtension for the one extra surface tone (panel background)
/// that ColorScheme's fixed role set doesn't cleanly cover post-M3.
class _Surfaces extends ThemeExtension<_Surfaces> {
  final Color panel;
  final Color border;

  const _Surfaces({required this.panel, required this.border});

  @override
  _Surfaces copyWith({Color? panel, Color? border}) =>
      _Surfaces(panel: panel ?? this.panel, border: border ?? this.border);

  @override
  _Surfaces lerp(ThemeExtension<_Surfaces>? other, double t) {
    if (other is! _Surfaces) return this;
    return _Surfaces(
      panel: Color.lerp(panel, other.panel, t) ?? panel,
      border: Color.lerp(border, other.border, t) ?? border,
    );
  }
}

extension AppSurfaces on ThemeData {
  Color get panelColor => extension<_Surfaces>()?.panel ?? colorScheme.surface;
  Color get borderColor => extension<_Surfaces>()?.border ?? dividerColor;
}
