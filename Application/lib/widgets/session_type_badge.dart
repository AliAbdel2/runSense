import 'package:flutter/material.dart';

import '../models/session.dart';

/// Small icon + label for a session's type. Shared by Home and Week Plan so
/// "hard day" always reads the same way everywhere, and so session type is
/// never conveyed by color alone.
class SessionTypeBadge extends StatelessWidget {
  final SessionType type;
  final Color? color;

  const SessionTypeBadge({super.key, required this.type, this.color});

  (IconData, String) _visuals() {
    switch (type) {
      case SessionType.hard:
        return (Icons.bolt, 'Hard');
      case SessionType.easy:
        return (Icons.directions_run, 'Easy');
      case SessionType.longRun:
        return (Icons.route, 'Long run');
      case SessionType.rest:
        return (Icons.bedtime, 'Rest');
    }
  }

  @override
  Widget build(BuildContext context) {
    final (icon, label) = _visuals();
    final tint = color ?? Theme.of(context).textTheme.bodyMedium?.color;
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        Icon(icon, size: 18, color: tint),
        const SizedBox(width: 6),
        Text(
          label,
          style: Theme.of(context)
              .textTheme
              .bodyMedium
              ?.copyWith(color: tint, fontWeight: FontWeight.w600),
        ),
      ],
    );
  }
}
