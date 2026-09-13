import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import 'app_config.dart';
import 'features/obstacle_detection/obstacle_detection_entry.dart';
import 'screens/home_screen.dart';
import 'services/agent_chat_service.dart';
import 'services/live/live_agent_chat_service.dart';
import 'services/live/live_location_service.dart';
import 'services/live/live_plan_service.dart';
import 'services/live/live_session_service.dart';
import 'services/location_service.dart';
import 'services/mock/mock_agent_chat_service.dart';
import 'services/mock/mock_location_service.dart';
import 'services/mock/mock_perception_service.dart';
import 'services/mock/mock_plan_service.dart';
import 'services/mock/mock_session_service.dart';
import 'services/perception_service.dart';
import 'services/plan_service.dart';
import 'services/session_service.dart';
import 'services/tts_service.dart';
import 'theme/app_theme.dart';

void main() {
  runApp(const RunSenseApp());
}

class RunSenseApp extends StatelessWidget {
  const RunSenseApp({super.key, this.forceMocks = false});

  /// Test seam: forces every service (including perception) to its mock,
  /// so widget tests never try to open a real camera. See app_config.dart.
  final bool forceMocks;

  @override
  Widget build(BuildContext context) {
    return MultiProvider(
      providers: [
        // TtsService is first because PerceptionService reads it during
        // creation — MultiProvider nests in list order, so a provider can only
        // read the ones declared above it.
        Provider<TtsService>(create: (_) => TtsService()),
        Provider<PlanService>(
          create: (_) => (forceMocks || useMockPlan)
              ? MockPlanService()
              : LivePlanService(),
        ),
        Provider<SessionService>(
          create: (_) => (forceMocks || useMockSession)
              ? MockSessionService()
              : LiveSessionService(),
          dispose: (_, service) {
            if (service is LiveSessionService) service.dispose();
          },
        ),
        Provider<PerceptionService>(
          create: (ctx) => (!forceMocks &&
                  !useMockPerception &&
                  obstacleDetectionSupported)
              ? createLivePerceptionService(ctx.read<TtsService>())
              : MockPerceptionService(),
          dispose: (_, service) => service.dispose(),
        ),
        Provider<AgentChatService>(
          create: (_) => (forceMocks || useMockAgentChat)
              ? MockAgentChatService()
              : LiveAgentChatService(),
        ),
        Provider<LocationService>(
          create: (_) => (forceMocks || useMockLocation)
              ? MockLocationService()
              : LiveLocationService(),
          dispose: (_, service) {
            if (service is MockLocationService) service.dispose();
            if (service is LiveLocationService) service.dispose();
          },
        ),
      ],
      child: MaterialApp(
        title: 'RunSense',
        theme: AppTheme.light,
        darkTheme: AppTheme.dark,
        themeMode: ThemeMode.system,
        home: const HomeScreen(),
      ),
    );
  }
}
