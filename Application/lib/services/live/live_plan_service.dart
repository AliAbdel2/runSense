import 'dart:convert';

import 'package:http/http.dart' as http;

import '../../models/guide_status.dart';
import '../../models/session.dart';
import '../api_config.dart';
import '../plan_service.dart';

/// Backed by POST /api/plan (app/routes/plan_routes.py -> PlanService.create,
/// safety-gated per app/services/plan_validation.py).
///
/// Note: that endpoint generates a plan on every call — there's no GET that
/// reads back a previously generated week, so both getWeekPlan() and
/// requestReplan() insert a fresh plan_weeks/sessions row each time. Fine
/// for a demo (the content is stable given the same trailing activities and
/// scenario); a real "read the current week" endpoint would need a
/// created_at column on PlanWeek to pick the latest row unambiguously.
class LivePlanService implements PlanService {
  @override
  Future<List<PlannedSession>> getWeekPlan(String athleteId) => _createPlan('baseline');

  @override
  Future<void> requestReplan(String reason) async {
    // The backend takes an enum scenario, not free text. The only caller
    // today (WeekPlanScreen's long-press) always means "guide cancelled".
    await _createPlan('guide_cancelled');
  }

  Future<List<PlannedSession>> _createPlan(String scenario) async {
    final response = await http.post(
      Uri.parse('$apiBaseUrl/api/plan'),
      headers: {'Content-Type': 'application/json'},
      body: jsonEncode({'scenario': scenario}),
    );
    if (response.statusCode != 200) {
      throw Exception('Plan generation failed (${response.statusCode}): ${response.body}');
    }
    final body = jsonDecode(response.body) as Map<String, dynamic>;
    final sessions = body['sessions'] as List<dynamic>;
    return sessions
        .map((raw) => _toPlannedSession(raw as Map<String, dynamic>))
        .toList();
  }

  PlannedSession _toPlannedSession(Map<String, dynamic> raw) {
    final kind = raw['kind'] as String;
    final km = (raw['km'] as num).toDouble();
    return PlannedSession(
      id: raw['id'] as String,
      date: raw['date'] as String,
      type: _sessionType(kind),
      description: _description(kind, km),
      spokenSummary: raw['spoken_summary'] as String,
      guideStatus: _guideStatus(raw['guide_status'] as String),
      venue: raw['venue'] as String,
    );
  }

  SessionType _sessionType(String kind) {
    switch (kind) {
      case 'rest':
        return SessionType.rest;
      case 'long':
        return SessionType.longRun;
      case 'intervals':
        return SessionType.hard;
      case 'easy':
      default:
        return SessionType.easy;
    }
  }

  GuideStatus _guideStatus(String value) {
    switch (value) {
      case 'accepted':
        return GuideStatus.accepted;
      case 'declined':
        return GuideStatus.declined;
      case 'not_required':
        return GuideStatus.notNeeded;
      default:
        return GuideStatus.pending;
    }
  }

  // The backend has no separate "description" field (only spoken_summary and
  // rationale, both longer/differently-worded) — build the short label the
  // Week Plan / Home screens expect from kind + distance.
  String _description(String kind, double km) {
    if (kind == 'rest') return 'Rest day';
    final kmLabel = km == km.roundToDouble() ? km.toStringAsFixed(0) : km.toStringAsFixed(1);
    switch (kind) {
      case 'intervals':
        return '${kmLabel}km intervals';
      case 'long':
        return '${kmLabel}km long run';
      default:
        return '${kmLabel}km easy run';
    }
  }
}
