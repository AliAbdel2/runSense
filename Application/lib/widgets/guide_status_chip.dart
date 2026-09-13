import 'package:flutter/material.dart';

import '../models/guide_status.dart';

/// Guide status indicator for the Week Plan list (plan section 6.3).
/// Icon + text + color together — never color alone, per the plan's
/// accessibility rule.
class GuideStatusChip extends StatelessWidget {
  final GuideStatus status;

  const GuideStatusChip({super.key, required this.status});

  (Color, IconData, String) _visuals() {
    switch (status) {
      case GuideStatus.accepted:
        return (Colors.green.shade700, Icons.check_circle, 'Guide confirmed');
      case GuideStatus.pending:
        return (Colors.amber.shade800, Icons.hourglass_top, 'Guide pending');
      case GuideStatus.declined:
        return (Colors.red.shade700, Icons.cancel, 'Guide declined');
      case GuideStatus.notNeeded:
        return (Colors.grey.shade600, Icons.block, 'No guide needed');
    }
  }

  @override
  Widget build(BuildContext context) {
    final (color, icon, label) = _visuals();
    return Semantics(
      label: label,
      child: Chip(
        avatar: Icon(icon, color: Colors.white, size: 18),
        label: Text(label, style: const TextStyle(color: Colors.white)),
        backgroundColor: color,
      ),
    );
  }
}
