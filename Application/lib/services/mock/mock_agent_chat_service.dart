import '../agent_chat_service.dart';

/// Pattern-matches keywords so the push-to-talk screen feels alive without
/// an LLM call. Extend the matches below as the demo script needs more.
class MockAgentChatService implements AgentChatService {
  @override
  Future<String> sendMessage(String text) async {
    await Future.delayed(const Duration(milliseconds: 400));
    final lower = text.toLowerCase();

    if (lower.contains('plan') && lower.contains('week')) {
      return "Done. I pulled your recent Strava runs and sent guide requests "
          "for Tuesday and Saturday, with a calendar invite for each.";
    }
    if (lower.contains('guide')) {
      return "I'll only request a guide on the days you've set: Tuesday and "
          "Saturday. Say 'plan my week' to rebuild the schedule.";
    }
    if (lower.contains('cancel') || lower.contains('replan')) {
      return "Got it. I'm adjusting the rest of your week to make up for that.";
    }
    return "I heard: \"$text\". Try asking me to plan your week.";
  }
}
