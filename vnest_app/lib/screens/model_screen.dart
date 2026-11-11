import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../data/scenario.dart';
import '../main.dart';
import '../services/llm_service.dart';

/// For therapists and testers: model status, add verbs, and see what the model wrote.
class ModelScreen extends StatefulWidget {
  const ModelScreen({super.key, required this.services});
  final AppServices services;

  @override
  State<ModelScreen> createState() => _ModelScreenState();
}

class _ModelScreenState extends State<ModelScreen> {
  final _verbField = TextEditingController();
  String? _addMessage;
  bool _confirmClear = false;

  @override
  void dispose() {
    _verbField.dispose();
    super.dispose();
  }

  Future<void> _add() async {
    final err = await widget.services.scenarios.addVerb(_verbField.text);
    setState(() {
      _addMessage = err ?? 'Added. The helper will write exercises for it in the background.';
      if (err == null) _verbField.clear();
    });
  }

  @override
  Widget build(BuildContext context) {
    final llm = widget.services.llm;
    final sc = widget.services.scenarios;
    final t = Theme.of(context).textTheme;
    return Scaffold(
      appBar: AppBar(title: const Text('On-device AI helper')),
      body: ListenableBuilder(
        listenable: sc,
        builder: (context, _) => ListView(
          padding: const EdgeInsets.all(16),
          children: [
            Text(
              'The helper plays the therapist: for each verb it writes the who / what / where / when / why '
              'questions with 4 options and marks the right answer. The app checks the patient\'s taps against that answer. '
              'Everything runs on this phone, offline.',
              style: t.bodyLarge,
            ),
            const SizedBox(height: 16),
            Wrap(spacing: 8, runSpacing: 4, children: [
              for (final m in LlmService.models)
                ChoiceChip(
                  label: Text(m.label),
                  selected: llm.model.id == m.id,
                  // switching waits for the current exercise; avoid a frozen-looking tap
                  onSelected: llm.state == ModelState.loading || sc.writingVerb != null ? null : (_) => llm.select(m),
                ),
            ]),
            const SizedBox(height: 8),
            _kv('Model', llm.model.id),
            _kv('Status', llm.state.name + (llm.loadMs != null ? ' (started in ${(llm.loadMs! / 1000).toStringAsFixed(1)} s)' : '')),
            if (sc.writingVerb != null)
              _kv('Writing', '"${sc.writingVerb}", one question at a time: '
                  '${[for (final k in QKind.values) '${k.name}${sc.draft?.questions.containsKey(k) == true ? ' ✓' : ''}'].join(' · ')}'),
            if (llm.error != null) _kv('Error', llm.error!),
            if (llm.state == ModelState.missing && llm.modelDir != null) ...[
              const SizedBox(height: 8),
              Text('Copy the model to the phone over USB (about ${llm.model.size}):', style: t.bodyLarge),
              const SizedBox(height: 8),
              _command('adb push ${llm.model.id} /data/local/tmp/\n'
                  'adb shell mv /data/local/tmp/${llm.model.id} ${llm.modelDir}'),
              OutlinedButton(onPressed: llm.refresh, child: const Text('Check again')),
            ],
            SwitchListTile(
              contentPadding: EdgeInsets.zero,
              title: const Text('Write exercises automatically'),
              subtitle: const Text('Turn off to test a new model with the buttons below first.'),
              value: llm.autoWrite,
              onChanged: llm.setAutoWrite,
            ),
            if (llm.state == ModelState.notLoaded || llm.state == ModelState.error)
              FilledButton(onPressed: llm.load, child: const Text('Start the helper')),
            if (llm.isReady) ...[
              const SizedBox(height: 8),
              Text('Self-test (tiny request)', style: t.titleMedium),
              Wrap(spacing: 8, runSpacing: 8, children: [
                OutlinedButton(
                  onPressed: llm.selfTestRunning || sc.writingVerb != null ? null : () => llm.selfTest(jsonRule: false),
                  child: const Text('Say hello (no JSON rule)'),
                ),
                OutlinedButton(
                  onPressed: llm.selfTestRunning || sc.writingVerb != null ? null : () => llm.selfTest(jsonRule: true),
                  child: const Text('Say hello (with JSON rule)'),
                ),
                OutlinedButton(
                  onPressed: llm.selfTestRunning || sc.writingVerb != null
                      ? null
                      : () => llm.selfTest(jsonRule: false, examplePrompt: true),
                  child: const Text('Read the exercise prompt'),
                ),
              ]),
            ],
            if (llm.selfTestResult != null) _kv('Test', llm.selfTestResult!),
            const SizedBox(height: 24),

            Text('Add a verb', style: t.titleLarge),
            const SizedBox(height: 4),
            Text('Stands in for the therapist adding verbs in the backend.', style: t.bodyMedium),
            const SizedBox(height: 8),
            Row(children: [
              Expanded(
                child: TextField(
                  controller: _verbField,
                  decoration: const InputDecoration(hintText: 'e.g. wash', border: OutlineInputBorder()),
                  textInputAction: TextInputAction.done,
                  onSubmitted: (_) => _add(),
                ),
              ),
              const SizedBox(width: 8),
              FilledButton(onPressed: _add, child: const Text('Add')),
            ]),
            if (_addMessage != null) Padding(padding: const EdgeInsets.only(top: 6), child: Text(_addMessage!)),
            const SizedBox(height: 24),

            Text('Exercises per verb', style: t.titleLarge),
            const SizedBox(height: 4),
            for (final v in sc.verbs)
              _kv(v, '${sc.modelScenarios(v).length} / 3'
                  '${sc.writingVerb == v ? '  · writing…' : ''}'
                  '${sc.lastError[v] != null ? '  · last try rejected: ${sc.lastError[v]}' : ''}'),
            const SizedBox(height: 24),

            Text('Latest from the model', style: t.titleLarge),
            if (sc.log.isEmpty) Text('Nothing yet.', style: t.bodyMedium),
            for (final r in sc.log) _ResultCard(r),
            const SizedBox(height: 24),

            if (!_confirmClear)
              TextButton(onPressed: () => setState(() => _confirmClear = true), child: const Text('Delete all AI-written exercises'))
            else
              Row(children: [
                Expanded(
                  child: FilledButton(
                    onPressed: () async {
                      await sc.clearGenerated();
                      setState(() => _confirmClear = false);
                    },
                    child: const Text('Delete and rewrite'),
                  ),
                ),
                const SizedBox(width: 12),
                Expanded(child: OutlinedButton(onPressed: () => setState(() => _confirmClear = false), child: const Text('Keep'))),
              ]),
          ],
        ),
      ),
    );
  }

  Widget _kv(String k, String v) => Padding(
        padding: const EdgeInsets.symmetric(vertical: 3),
        child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
          SizedBox(width: 90, child: Text(k, style: Theme.of(context).textTheme.labelLarge)),
          Expanded(child: SelectableText(v)),
        ]),
      );

  Widget _command(String cmd) => Container(
        padding: const EdgeInsets.all(12),
        decoration: BoxDecoration(color: Theme.of(context).colorScheme.surfaceContainerHighest, borderRadius: BorderRadius.circular(8)),
        child: Row(children: [
          Expanded(child: SelectableText(cmd, style: const TextStyle(fontFamily: 'monospace', fontSize: 13))),
          IconButton(icon: const Icon(Icons.copy), tooltip: 'Copy', onPressed: () => Clipboard.setData(ClipboardData(text: cmd))),
        ]),
      );
}

/// One generation: the questions (answer marked ✓) or why it was rejected, plus timing.
class _ResultCard extends StatelessWidget {
  const _ResultCard(this.r);
  final ScenarioResult r;

  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context).textTheme;
    final s = r.scenario;
    final timing = [
      if (r.model != null) r.model!,
      if (r.ms != null) '${(r.ms! / 1000).toStringAsFixed(0)} s',
      if (r.tokens != null) '${r.tokens} tokens',
      if (r.tps != null) '${r.tps!.toStringAsFixed(1)} tokens/s',
    ].join(' · ');
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          if (s != null) ...[
            Text(s.sentence, style: t.titleMedium),
            for (final k in QKind.values)
              Text('${k.name}: ${s.questions[k]!.options.map((o) => o == s.questions[k]!.answer ? '✓$o' : o).join(' / ')}',
                  style: t.bodyMedium),
          ] else ...[
            Text('Rejected: ${r.rejectedReason}', style: t.titleSmall?.copyWith(color: Theme.of(context).colorScheme.error)),
            if (r.rawText != null)
              Text(r.rawText!.length > 300 ? '${r.rawText!.substring(0, 300)}…' : r.rawText!, style: t.bodySmall),
          ],
          const SizedBox(height: 4),
          Text(timing, style: t.bodySmall),
        ]),
      ),
    );
  }
}
