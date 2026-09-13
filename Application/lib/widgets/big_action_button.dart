import 'package:flutter/material.dart';

/// The >=64px touch-target button pattern used on every screen. Primary
/// actions (Start Session) use the filled style; secondary ones (Ask Coach)
/// use the outlined style — never color alone to distinguish state.
class BigActionButton extends StatelessWidget {
  final String label;
  final String? semanticLabel;
  final VoidCallback? onPressed;
  final bool primary;

  const BigActionButton({
    super.key,
    required this.label,
    required this.onPressed,
    this.semanticLabel,
    this.primary = true,
  });

  @override
  Widget build(BuildContext context) {
    final textStyle = TextStyle(
      fontSize: primary ? 22 : 18,
      fontWeight: primary ? FontWeight.bold : FontWeight.w600,
    );

    final button = primary
        ? ElevatedButton(
            onPressed: onPressed,
            style: ElevatedButton.styleFrom(
              minimumSize: const Size.fromHeight(72),
              textStyle: textStyle,
            ),
            child: Text(label),
          )
        : OutlinedButton(
            onPressed: onPressed,
            style: OutlinedButton.styleFrom(
              minimumSize: const Size.fromHeight(64),
              textStyle: textStyle,
            ),
            child: Text(label),
          );

    return Semantics(
      button: true,
      label: semanticLabel ?? label,
      child: SizedBox(width: double.infinity, child: button),
    );
  }
}
