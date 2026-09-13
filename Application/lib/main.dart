import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import 'app_config.dart';
import 'features/obstacle_detection/obstacle_detection_entry.dart';
import 'screens/home_screen.dart';
import 'services/agent_chat_service.dart';
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

void main() {
  runApp(const RunSenseApp());
}

class RunSenseApp extends StatelessWidget {
  const RunSenseApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MultiProvider(
      providers: [
        // TtsService is first because PerceptionService reads it during
        // creation — MultiProvider nests in list order, so a provider can only
        // read the ones declared above it.
        Provider<TtsService>(create: (_) => TtsService()),
        Provider<PlanService>(
          create: (_) => useMock
              ? MockPlanService()
              : throw UnimplementedError('LivePlanService not wired yet'),
        ),
        Provider<SessionService>(
          create: (_) => useMock
              ? MockSessionService()
              : throw UnimplementedError('LiveSessionService not wired yet'),
        ),
        Provider<PerceptionService>(
          create: (ctx) => useMock
              ? MockPerceptionService()
              : createLivePerceptionService(ctx.read<TtsService>()),
        ),
        Provider<AgentChatService>(
          create: (_) => useMock
              ? MockAgentChatService()
              : throw UnimplementedError('LiveAgentChatService not wired yet'),
        ),
        // Not yet consumed by any screen — added ahead of the real GPS work
        // so the eventual LiveLocationService is a one-file swap.
        Provider<LocationService>(
          create: (_) => useMock
              ? MockLocationService()
              : throw UnimplementedError('LiveLocationService not wired yet'),
        ),
      ],
      child: MaterialApp(
        title: 'RunSense',
        theme: ThemeData(
          colorScheme: ColorScheme.fromSeed(seedColor: Colors.deepPurple),
          useMaterial3: true,
        ),
        home: const HomeScreen(),
        routes: {
          obstacleDetectionRoute: buildObstacleDetectionScreen,
        },
      ),
    );
  }
}
