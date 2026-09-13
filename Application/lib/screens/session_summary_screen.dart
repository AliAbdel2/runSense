import 'package:flutter/material.dart';

import '../models/session.dart';
import '../widgets/big_action_button.dart';

/// Shown after "End session" on the Live Run screen. Reads whatever
/// SessionService.endSession() produced (see LiveRunScreen._endSession) —
/// nothing here is mocked itself, it just displays the CompletedSession.
class SessionSummaryScreen extends StatelessWidget {
  final CompletedSession session;

  const SessionSummaryScreen({super.key, required this.session});

  String _formatDuration(Duration d) {
    final minutes = d.inMinutes;
    final seconds = d.inSeconds % 60;
    return '$minutes min ${seconds.toString().padLeft(2, '0')} sec';
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Session Summary'), automaticallyImplyLeading: false),
      body: SafeArea(
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Semantics(
                liveRegion: true,
                child: Text(
                  'Session complete',
                  style: Theme.of(context).textTheme.headlineSmall,
                ),
              ),
              const SizedBox(height: 24),
              _StatRow(label: 'Distance', value: '${session.actualKm.toStringAsFixed(1)} km'),
              const SizedBox(height: 12),
              _StatRow(label: 'Duration', value: _formatDuration(session.duration)),
              const SizedBox(height: 12),
              _StatRow(label: 'Alerts', value: '${session.alertCount}'),
              if (session.adaptationNote != null) ...[
                const SizedBox(height: 24),
                Semantics(
                  liveRegion: true,
                  child: Container(
                    padding: const EdgeInsets.all(16),
                    decoration: BoxDecoration(
                      color: Theme.of(context).colorScheme.secondaryContainer,
                      borderRadius: BorderRadius.circular(12),
                    ),
                    child: Row(
                      children: [
                        const Icon(Icons.autorenew),
                        const SizedBox(width: 12),
                        Expanded(child: Text(session.adaptationNote!)),
                      ],
                    ),
                  ),
                ),
              ],
              const Spacer(),
              BigActionButton(
                label: 'DONE',
                semanticLabel: 'Done, back to home',
                onPressed: () => Navigator.of(context).pop(),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _StatRow extends StatelessWidget {
  final String label;
  final String value;

  const _StatRow({required this.label, required this.value});

  @override
  Widget build(BuildContext context) {
    return Semantics(
      label: '$label: $value',
      child: Row(
        mainAxisAlignment: MainAxisAlignment.spaceBetween,
        children: [
          Text(label, style: Theme.of(context).textTheme.bodyLarge),
          Text(
            value,
            style: Theme.of(context)
                .textTheme
                .bodyLarge
                ?.copyWith(fontWeight: FontWeight.bold),
          ),
        ],
      ),
    );
  }
}
