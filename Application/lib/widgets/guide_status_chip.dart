import 'package:flutter/material.dart';

import '../models/guide_status.dart';
import '../theme/app_colors.dart';

/// Guide status indicator for the Week Plan list (plan section 6.3).
/// Icon + text + color together — never color alone, per the plan's
/// accessibility rule. Colors are shared with Live Run's alert tiers
/// (warning/danger) so the same hue always means the same thing app-wide.
class GuideStatusChip extends StatelessWidget {
  final GuideStatus status;

  const GuideStatusChip({super.key, required this.status});

  (Color, IconData, String) _visuals() {
    switch (status) {
      case GuideStatus.accepted:
        return (AppSemanticColors.accepted, Icons.check_circle, 'Guide confirmed');
      case GuideStatus.pending:
        return (AppSemanticColors.warning, Icons.hourglass_top, 'Guide pending');
      case GuideStatus.declined:
        return (AppSemanticColors.danger, Icons.cancel, 'Guide declined');
      case GuideStatus.notNeeded:
        return (AppSemanticColors.neutral, Icons.block, 'No guide needed');
    }
  }

  @override
  Widget build(BuildContext context) {
    final (color, icon, label) = _visuals();
    return Semantics(
      label: label,
      child: Chip(
        avatar: Icon(icon, color: AppSemanticColors.onFill, size: 18),
        label: Text(label, style: const TextStyle(color: AppSemanticColors.onFill)),
        backgroundColor: color,
        padding: const EdgeInsets.symmetric(horizontal: 4),
      ),
    );
  }
}
