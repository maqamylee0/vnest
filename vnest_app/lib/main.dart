import 'package:flutter/material.dart';

import 'data/verb_network.dart';
import 'screens/home_screen.dart';
import 'services/llm_service.dart';
import 'services/progress_store.dart';
import 'services/scenario_service.dart';

void main() {
  WidgetsFlutterBinding.ensureInitialized();
  runApp(VnestApp(services: AppServices()));
}

/// The app's long-lived services, created once and passed down.
class AppServices {
  AppServices() {
    scenarios = ScenarioService(llm, verbs);
    _start();
  }

  final verbs = VerbRepository();
  final llm = LlmService();
  final progress = ProgressStore();
  late final ScenarioService scenarios;

  /// The model does NOT start by itself (it slows the phone); use Start on the AI helper card.
  Future<void> _start() async {
    await scenarios.init();
    await llm.refresh();
  }
}

class VnestApp extends StatelessWidget {
  const VnestApp({super.key, required this.services});
  final AppServices services;

  @override
  Widget build(BuildContext context) {
    // Large type and generous targets: users may have aphasia and motor difficulties.
    ThemeData theme(Brightness b) {
      final scheme = ColorScheme.fromSeed(seedColor: const Color(0xFF1F6F6A), brightness: b);
      final base = ThemeData(colorScheme: scheme, useMaterial3: true);
      return base.copyWith(
        textTheme: base.textTheme.apply(fontSizeFactor: 1.15),
        filledButtonTheme: FilledButtonThemeData(
          style: FilledButton.styleFrom(minimumSize: const Size(64, 56), textStyle: const TextStyle(fontSize: 20)),
        ),
        outlinedButtonTheme: OutlinedButtonThemeData(
          style: OutlinedButton.styleFrom(minimumSize: const Size(64, 56), textStyle: const TextStyle(fontSize: 20)),
        ),
      );
    }

    return MaterialApp(
      title: 'VNeST Practice',
      debugShowCheckedModeBanner: false,
      theme: theme(Brightness.light),
      darkTheme: theme(Brightness.dark),
      home: HomeScreen(services: services),
    );
  }
}
