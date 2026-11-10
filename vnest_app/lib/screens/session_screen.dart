import 'dart:math';

import 'package:flutter/material.dart';

import '../data/scenario.dart';
import '../main.dart';
import '../services/progress_store.dart';

/// One item in the session queue: a multiple-choice question or a sense-check sentence.
class _Item {
  _Item.question(this.scenario, this.kind)
      : sentence = null,
        makesSense = null;
  _Item.sentence(this.scenario, this.sentence, this.makesSense) : kind = null;

  final Scenario scenario;
  final QKind? kind; // set for questions
  final String? sentence; // set for sentence checks
  final bool? makesSense;

  PracticeStep get step => switch (kind) {
        QKind.who || QKind.what => PracticeStep.pairs,
        QKind.where || QKind.when || QKind.why => PracticeStep.questions,
        null => PracticeStep.sentences,
      };
}

/// One VNeST session for one verb. All answers are checked by code against the
/// answer the model (or the reviewed list) marked as correct.
///  1. For each scenario: "Who cooks?" then "What does the chef cook?"
///  2. Where / when / why about the first scenario
///  3. Does it make sense? (correct sentence, swapped roles, wrong object)
class SessionScreen extends StatefulWidget {
  const SessionScreen({super.key, required this.services, required this.verb, required this.scenarios});
  final AppServices services;
  final String verb;
  final List<Scenario> scenarios;

  @override
  State<SessionScreen> createState() => _SessionScreenState();
}

class _SessionScreenState extends State<SessionScreen> {
  late final List<_Item> _items = _buildQueue();
  int _index = 0;
  final Set<String> _wrongTapped = {};
  String? _correctTapped;
  bool? _sentenceFeedback;
  int _tries = 0;
  DateTime _itemStart = DateTime.now();
  final Map<PracticeStep, int> _firstTry = {for (final s in PracticeStep.values) s: 0};
  final Map<PracticeStep, int> _total = {for (final s in PracticeStep.values) s: 0};

  bool get _done => _index >= _items.length;
  _Item get _item => _items[_index];

  List<_Item> _buildQueue() {
    final scs = widget.scenarios;
    final first = scs.first;
    final rng = Random();
    final wrongWhat = first.questions[QKind.what]!.options.where((o) => o != first.patient).toList()..shuffle(rng);
    final sentences = <_Item>[
      for (final s in scs.take(2)) _Item.sentence(s, s.sentence, true),
      _Item.sentence(first, 'The ${first.patient} ${first.verb3} the ${first.agent}.', false), // swapped roles
      _Item.sentence(first, 'The ${first.agent} ${first.verb3} the ${wrongWhat.first}.', false), // wrong object
    ]..shuffle(rng);
    return [
      for (final s in scs) ...[_Item.question(s, QKind.who), _Item.question(s, QKind.what)],
      for (final k in [QKind.where, QKind.when, QKind.why]) _Item.question(first, k),
      ...sentences,
    ];
  }

  Future<void> _record({required bool firstTry}) async {
    final step = _item.step;
    _total[step] = _total[step]! + 1;
    if (firstTry) _firstTry[step] = _firstTry[step]! + 1;
    await widget.services.progress.record(Attempt(
      verb: widget.verb,
      step: step,
      firstTry: firstTry,
      tries: _tries,
      ms: DateTime.now().difference(_itemStart).inMilliseconds,
      at: DateTime.now(),
      fromModel: _item.scenario.source == ScenarioSource.llm,
    ));
  }

  Future<void> _next() async {
    await Future.delayed(const Duration(milliseconds: 900));
    if (!mounted) return;
    setState(() {
      _index++;
      _wrongTapped.clear();
      _correctTapped = null;
      _sentenceFeedback = null;
      _tries = 0;
      _itemStart = DateTime.now();
      if (_done) widget.services.progress.sessionCompleted();
    });
  }

  /// The check: is the tapped option the answer marked correct?
  Future<void> _tapOption(String option) async {
    if (_correctTapped != null || _wrongTapped.contains(option)) return;
    _tries++;
    final q = _item.scenario.questions[_item.kind]!;
    if (!q.isCorrect(option)) {
      setState(() => _wrongTapped.add(option));
      return;
    }
    setState(() => _correctTapped = option);
    await _record(firstTry: _tries == 1);
    await _next();
  }

  void _hint() {
    final q = _item.scenario.questions[_item.kind]!;
    final wrong = q.options.where((o) => o != q.answer && !_wrongTapped.contains(o)).toList();
    if (wrong.length <= 1) return;
    setState(() {
      _tries++;
      _wrongTapped.add(wrong.first);
    });
  }

  Future<void> _judge(bool saysSense) async {
    if (_sentenceFeedback == true) return;
    _tries++;
    final right = saysSense == _item.makesSense;
    setState(() => _sentenceFeedback = right);
    if (!right) return;
    await _record(firstTry: _tries == 1);
    await _next();
  }

  // ---------------- UI ----------------
  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: Text(widget.verb, style: const TextStyle(fontSize: 28, fontWeight: FontWeight.w700)),
        bottom: PreferredSize(
          preferredSize: const Size.fromHeight(6),
          child: LinearProgressIndicator(value: _done ? 1 : _index / _items.length),
        ),
      ),
      body: SafeArea(
        child: Padding(
          padding: const EdgeInsets.all(16),
          child: _done ? _doneView(context) : (_item.kind != null ? _questionView(context) : _sentenceView(context)),
        ),
      ),
    );
  }

  Widget _stepLabel(BuildContext context) {
    final label = switch (_item.step) {
      PracticeStep.pairs => 'STEP 1 OF 3  ·  ${_item.kind == QKind.who ? 'WHO' : 'WHAT'}',
      PracticeStep.questions => 'STEP 2 OF 3  ·  ${_item.kind!.name.toUpperCase()}',
      PracticeStep.sentences => 'STEP 3 OF 3',
    };
    return Text(label, style: Theme.of(context).textTheme.labelLarge?.copyWith(color: Theme.of(context).colorScheme.primary));
  }

  Widget _questionView(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final s = _item.scenario;
    final kind = _item.kind!;
    final q = s.questions[kind]!;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        _stepLabel(context),
        const SizedBox(height: 12),
        // Keep what's already known on screen, so nothing has to be held in memory.
        if (kind == QKind.what)
          Padding(
            padding: const EdgeInsets.only(bottom: 8),
            child: Row(children: [
              Chip(avatar: const Icon(Icons.person, size: 20), label: Text(s.agent, style: const TextStyle(fontSize: 20))),
              const SizedBox(width: 8),
              Text('${s.verb3} …?', style: Theme.of(context).textTheme.titleLarge),
            ]),
          ),
        if (kind != QKind.who && kind != QKind.what)
          Padding(
            padding: const EdgeInsets.only(bottom: 8),
            child: Text(s.sentence, style: Theme.of(context).textTheme.titleLarge),
          ),
        Text(s.prompt(kind), style: Theme.of(context).textTheme.headlineMedium?.copyWith(fontWeight: FontWeight.w600)),
        const SizedBox(height: 20),
        Expanded(
          child: ListView.separated(
            itemCount: q.options.length,
            separatorBuilder: (_, _) => const SizedBox(height: 12),
            itemBuilder: (context, i) {
              final o = q.options[i];
              final wrong = _wrongTapped.contains(o);
              final right = _correctTapped == o;
              return Opacity(
                opacity: wrong ? 0.35 : 1,
                child: Material(
                  color: right ? Colors.green.withValues(alpha: .25) : scheme.surfaceContainerHigh,
                  borderRadius: BorderRadius.circular(16),
                  child: InkWell(
                    borderRadius: BorderRadius.circular(16),
                    onTap: () => _tapOption(o),
                    child: Padding(
                      padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 20),
                      child: Row(children: [
                        Expanded(child: Text(o, style: const TextStyle(fontSize: 26, fontWeight: FontWeight.w600))),
                        if (right) const Icon(Icons.check_circle, color: Colors.green, size: 34),
                        if (wrong) Icon(Icons.close, color: scheme.error, size: 34),
                      ]),
                    ),
                  ),
                ),
              );
            },
          ),
        ),
        if (s.source == ScenarioSource.llm)
          Padding(
            padding: const EdgeInsets.only(bottom: 8),
            child: Text('Written by the on-device AI', textAlign: TextAlign.center, style: Theme.of(context).textTheme.bodySmall),
          ),
        OutlinedButton.icon(onPressed: _correctTapped == null ? _hint : null, icon: const Icon(Icons.lightbulb_outline), label: const Text('Hint')),
      ],
    );
  }

  Widget _sentenceView(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        _stepLabel(context),
        const SizedBox(height: 8),
        Text('Does this make sense?', style: Theme.of(context).textTheme.headlineMedium),
        const SizedBox(height: 32),
        Card(
          child: Padding(
            padding: const EdgeInsets.all(24),
            child: Text(_item.sentence!, textAlign: TextAlign.center, style: const TextStyle(fontSize: 30, fontWeight: FontWeight.w600)),
          ),
        ),
        const SizedBox(height: 16),
        if (_sentenceFeedback != null)
          Text(
            _sentenceFeedback! ? 'Yes, that\'s right.' : 'Not quite. Try again.',
            textAlign: TextAlign.center,
            style: TextStyle(fontSize: 22, color: _sentenceFeedback! ? Colors.green : scheme.error),
          ),
        const Spacer(),
        Row(children: [
          Expanded(child: FilledButton.icon(onPressed: () => _judge(true), icon: const Icon(Icons.thumb_up), label: const Text('Makes sense'))),
          const SizedBox(width: 12),
          Expanded(child: OutlinedButton.icon(onPressed: () => _judge(false), icon: const Icon(Icons.thumb_down), label: const Text('No sense'))),
        ]),
      ],
    );
  }

  Widget _doneView(BuildContext context) {
    String line(String label, PracticeStep s) => '$label: ${_firstTry[s]} of ${_total[s]}';
    final t = Theme.of(context).textTheme;
    return Column(
      mainAxisAlignment: MainAxisAlignment.center,
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        const Icon(Icons.celebration, size: 72),
        const SizedBox(height: 16),
        Text('Well done!', textAlign: TextAlign.center, style: t.headlineLarge),
        const SizedBox(height: 24),
        Text(line('Who and what, first try', PracticeStep.pairs), textAlign: TextAlign.center, style: t.titleMedium),
        Text(line('Where, when, why, first try', PracticeStep.questions), textAlign: TextAlign.center, style: t.titleMedium),
        Text(line('Sentences, first try', PracticeStep.sentences), textAlign: TextAlign.center, style: t.titleMedium),
        const SizedBox(height: 32),
        FilledButton(onPressed: () => Navigator.pop(context), child: const Text('Back to words')),
      ],
    );
  }
}
