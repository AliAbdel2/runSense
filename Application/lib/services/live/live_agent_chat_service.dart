import 'dart:convert';

import 'package:http/http.dart' as http;

import '../agent_chat_service.dart';
import '../api_config.dart';

/// Backed by POST /v1/agent/chat (app/routes/agent_routes.py -> run_agent).
///
class LiveAgentChatService implements AgentChatService {
  @override
  Future<String> sendMessage(String text) async {
    final response = await http.post(
      Uri.parse('$apiBaseUrl/v1/agent/chat'),
      headers: apiJsonHeaders(),
      body: jsonEncode({'question': text}),
    );
    if (response.statusCode != 200) {
      throw Exception('Agent chat failed (${response.statusCode}): ${response.body}');
    }
    final body = jsonDecode(response.body) as Map<String, dynamic>;
    return body['answer'] as String;
  }
}
