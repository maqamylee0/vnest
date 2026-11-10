import 'package:flutter/material.dart';

import '../services/progress_store.dart';

class ProgressScreen extends StatefulWidget {
  const ProgressScreen({super.key, required this.store});
  final ProgressStore store;

  @override
  State<ProgressScreen> createState() => _ProgressScreenState();
}

class _ProgressScreenState extends State<ProgressScreen> {
  late Future<ProgressSummary> _summary = widget.store.summary();
  bool _confirmClear = false;

  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context).textTheme;
    return Scaffold(
      appBar: AppBar(title: const Text('My progress')),
      body: FutureBuilder<ProgressSummary>(
        future: _summary,
        builder: (context, snap) {
          if (!snap.hasData) return const Center(child: CircularProgressIndicator());
          final s = snap.data!;
          if (s.thisWeek.attempts == 0 && s.lastWeek.attempts == 0) {
            return Center(
              child: Padding(
                padding: const EdgeInsets.all(24),
                child: Text('No practice yet. Choose a word on the main screen to start.', textAlign: TextAlign.center, style: t.titleLarge),
              ),
            );
          }
          final change = (s.thisWeek.pct != null && s.lastWeek.pct != null) ? s.thisWeek.pct! - s.lastWeek.pct! : null;
          return ListView(
            padding: const EdgeInsets.all(16),
            children: [
              _big(context, '${s.thisWeek.pct ?? 0}%', 'right on the first try this week'),
              if (change != null)
                Padding(
                  padding: const EdgeInsets.only(top: 4, bottom: 8),
                  child: Text(
                    change >= 0 ? 'Up $change points from last week (${s.lastWeek.pct}%).' : 'Down ${-change} points from last week (${s.lastWeek.pct}%).',
                    style: t.titleMedium,
                  ),
                ),
              const SizedBox(height: 8),
              Text('${s.sessions} sessions finished · ${s.thisWeek.attempts} answers this week'
                  '${s.medianSeconds != null ? ' · typical answer ${s.medianSeconds!.toStringAsFixed(1)} s' : ''}', style: t.bodyLarge),
              const SizedBox(height: 24),
              Text('This week by step', style: t.titleLarge),
              const SizedBox(height: 8),
              _stepRow(context, 'Who and what', s.byStep[PracticeStep.pairs]!),
              _stepRow(context, 'Where / when / why', s.byStep[PracticeStep.questions]!),
              _stepRow(context, 'Does it make sense?', s.byStep[PracticeStep.sentences]!),
              const SizedBox(height: 24),
              Text('Words to practise more', style: t.titleLarge),
              const SizedBox(height: 4),
              Text(s.needsPractice.isEmpty ? 'None right now.' : s.needsPractice.join(', '), style: t.bodyLarge),
              const SizedBox(height: 40),
              if (!_confirmClear)
                TextButton(onPressed: () => setState(() => _confirmClear = true), child: const Text('Clear all progress'))
              else
                Card(
                  child: Padding(
                    padding: const EdgeInsets.all(16),
                    child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
                      Text('Delete all saved answers on this phone?', style: t.titleMedium),
                      const SizedBox(height: 12),
                      Row(children: [
                        Expanded(
                          child: FilledButton(
                            onPressed: () async {
                              await widget.store.clear();
                              setState(() {
                                _confirmClear = false;
                                _summary = widget.store.summary();
                              });
                            },
                            child: const Text('Delete'),
                          ),
                        ),
                        const SizedBox(width: 12),
                        Expanded(child: OutlinedButton(onPressed: () => setState(() => _confirmClear = false), child: const Text('Keep'))),
                      ]),
                    ]),
                  ),
                ),
            ],
          );
        },
      ),
    );
  }

  Widget _big(BuildContext context, String value, String label) => Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(value, style: Theme.of(context).textTheme.displayMedium?.copyWith(fontWeight: FontWeight.w700)),
          Text(label, style: Theme.of(context).textTheme.titleMedium),
        ],
      );

  Widget _stepRow(BuildContext context, String label, StepStats s) => Padding(
        padding: const EdgeInsets.symmetric(vertical: 8),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Row(children: [
            Expanded(child: Text(label, style: Theme.of(context).textTheme.bodyLarge)),
            Text(s.attempts == 0 ? '–' : '${s.firstTry}/${s.attempts}', style: Theme.of(context).textTheme.titleMedium),
          ]),
          const SizedBox(height: 6),
          LinearProgressIndicator(value: s.attempts == 0 ? 0 : s.firstTry / s.attempts, minHeight: 10, borderRadius: BorderRadius.circular(5)),
        ]),
      );
}
