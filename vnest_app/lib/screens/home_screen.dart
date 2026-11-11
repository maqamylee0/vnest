import 'package:flutter/material.dart';

import '../main.dart';
import '../services/llm_service.dart';
import '../services/scenario_service.dart';
import 'model_screen.dart';
import 'progress_screen.dart';
import 'session_screen.dart';

class HomeScreen extends StatelessWidget {
  const HomeScreen({super.key, required this.services});
  final AppServices services;

  Future<void> _open(BuildContext context, String verb) async {
    // No stored AI exercise but the helper is running: write one now, question by question; the session starts on
    // "who" as soon as it is written and the rest arrive while the patient answers (RESEARCH_LOG decision 2026-11-11).
    if (services.scenarios.modelScenarios(verb).isEmpty && services.llm.isReady) {
      final live = services.scenarios.startLive(verb);
      Navigator.push(context, MaterialPageRoute(
        builder: (_) => SessionScreen(services: services, verb: verb, scenarios: const [], live: live),
      ));
      return;
    }
    final scenarios = await services.scenarios.forSession(verb);
    if (!context.mounted) return;
    if (scenarios.isEmpty) {
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(
        content: Text('"$verb" isn\'t ready yet. The AI helper writes it in the background.'),
      ));
      return;
    }
    Navigator.push(context, MaterialPageRoute(
      builder: (_) => SessionScreen(services: services, verb: verb, scenarios: scenarios),
    ));
  }

  @override
  Widget build(BuildContext context) {
    final sc = services.scenarios;
    return Scaffold(
      appBar: AppBar(
        title: const Text('Practice verbs'),
        actions: [
          IconButton(
            tooltip: 'My progress',
            icon: const Icon(Icons.insights),
            onPressed: () => Navigator.push(context, MaterialPageRoute(builder: (_) => ProgressScreen(store: services.progress))),
          ),
        ],
      ),
      body: ListenableBuilder(
        listenable: sc,
        builder: (context, _) => ListView(
          padding: const EdgeInsets.all(16),
          children: [
            _ModelCard(services: services),
            const SizedBox(height: 16),
            Text('Choose a word', style: Theme.of(context).textTheme.titleLarge),
            const SizedBox(height: 12),
            GridView.count(
              crossAxisCount: 2,
              shrinkWrap: true,
              physics: const NeverScrollableScrollPhysics(),
              mainAxisSpacing: 12,
              crossAxisSpacing: 12,
              childAspectRatio: 1.9,
              children: [for (final v in sc.verbs) _VerbButton(verb: v, sc: sc, onTap: () => _open(context, v))],
            ),
          ],
        ),
      ),
    );
  }
}

class _VerbButton extends StatelessWidget {
  const _VerbButton({required this.verb, required this.sc, required this.onTap});
  final String verb;
  final ScenarioService sc;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final n = sc.modelScenarios(verb).length;
    final status = switch (sc.status(verb)) {
      VerbStatus.writing => 'AI writing…',
      VerbStatus.ready => '$n AI exercise${n == 1 ? '' : 's'}',
      VerbStatus.failed => 'AI retrying',
      VerbStatus.reviewedOnly => 'reviewed list',
      VerbStatus.waitingForModel => 'waiting for AI',
    };
    return FilledButton.tonal(
      onPressed: onTap,
      style: FilledButton.styleFrom(shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(20))),
      child: Column(mainAxisSize: MainAxisSize.min, children: [
        Text(verb, style: const TextStyle(fontSize: 26, fontWeight: FontWeight.w600)),
        const SizedBox(height: 2),
        Text(status, style: Theme.of(context).textTheme.bodySmall),
      ]),
    );
  }
}

/// Status card for the therapist/tester.
class _ModelCard extends StatelessWidget {
  const _ModelCard({required this.services});
  final AppServices services;

  @override
  Widget build(BuildContext context) {
    final llm = services.llm;
    final sc = services.scenarios;
    final (icon, text) = switch (llm.state) {
      ModelState.checking => (Icons.hourglass_empty, 'Checking for the on-device helper…'),
      ModelState.missing => (Icons.cloud_off, 'Helper not installed. Only reviewed lists available.'),
      ModelState.notLoaded => (Icons.memory, 'Stopped. Tap Start to write more exercises.'),
      ModelState.loading => (Icons.downloading, 'Starting the helper on this phone…'),
      ModelState.ready => (
          Icons.check_circle,
          sc.writingVerb != null ? 'Writing an exercise for "${sc.writingVerb}"… (about 2 min each)' : 'Ready. All exercises written.'
        ),
      ModelState.error => (Icons.error_outline, 'Helper could not start. Only reviewed lists available.'),
    };
    final busy = llm.state == ModelState.loading || sc.writingVerb != null;
    final canStop = llm.state == ModelState.ready || llm.state == ModelState.loading;
    final canStart = llm.state == ModelState.notLoaded || llm.state == ModelState.error;
    return Card(
      child: ListTile(
        leading: busy ? const SizedBox(width: 24, height: 24, child: CircularProgressIndicator(strokeWidth: 3)) : Icon(icon),
        title: const Text('On-device AI helper'),
        subtitle: Text(sc.stopping ? 'Stopping after the current exercise…' : text),
        trailing: sc.stopping
            ? null
            : canStop
                ? OutlinedButton(onPressed: sc.stop, child: const Text('Stop'))
                : canStart
                    ? FilledButton(onPressed: sc.start, child: const Text('Start'))
                    : const Icon(Icons.chevron_right),
        onTap: () => Navigator.push(context, MaterialPageRoute(builder: (_) => ModelScreen(services: services))),
      ),
    );
  }
}
