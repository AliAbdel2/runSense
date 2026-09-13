import 'package:flutter/material.dart';

/// AppBar back button sized to the plan's 64px touch-target rule — the
/// default Material back arrow is only 48px.
class AccessibleBackButton extends StatelessWidget {
  const AccessibleBackButton({super.key});

  @override
  Widget build(BuildContext context) {
    return Semantics(
      button: true,
      label: 'Back',
      child: IconButton(
        icon: const Icon(Icons.arrow_back),
        constraints: const BoxConstraints(minWidth: 64, minHeight: 64),
        onPressed: () => Navigator.of(context).pop(),
      ),
    );
  }
}
