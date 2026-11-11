import 'dart:async';
import 'dart:convert';

import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../data/scenario.dart';

enum ModelState { checking, missing, notLoaded, loading, ready, error }

/// Result of asking the model for one scenario.
class ScenarioResult {
  const ScenarioResult({this.scenario, this.rejectedReason, this.rawText, this.ms, this.tokens, this.tps, this.model});
  final Scenario? scenario; // null = not usable
  final String? rejectedReason;
  final String? rawText; // what the model wrote (for the test screen)
  final int? ms;
  final int? tokens;
  final double? tps;
  final String? model; // LlmModel.label of the model that wrote it
}

/// One on-device model the app can run.
///
/// [lib] must be a model library compiled into libtvm4j_runtime_packed.so. The MLC LLM Android release
/// Android-09262024 packs: llama_q4f16_0 (Llama-3.2-3B), qwen2_q4f16_1 (Qwen2.5-1.5B), gemma2_q4f16_1,
/// phi3_q4f16_0, mistral_q4f16_1. A fine-tuned Qwen2.5-1.5B converted to q4f16_1 reuses the qwen2 library
/// under its own [id] (the weights folder name).
class LlmModel {
  const LlmModel({required this.id, required this.lib, required this.label, required this.size, this.engine = const {}});
  final String id; // weights folder under the app's external files dir
  final String lib;
  final String label;
  final String size; // shown in the copy-over-USB instructions
  /// Extra MLC EngineConfig fields passed at load time (memory / GPU-job limits). Empty = MLC defaults.
  final Map<String, Object> engine;
}

/// Runs an on-device LLM (via LlmChannel.kt / MLC LLM). The model plays the
/// therapist: for a verb, it writes the five questions with 4 options each and marks the
/// correct answer. The app's code then checks the patient's taps against that answer.
class LlmService extends ChangeNotifier {
  static const _channel = MethodChannel('vnest/llm');
  static const _modelKey = 'llm_model_v1';

  /// Same engine limits for every model, so speed comparisons are fair. With MLC defaults (32k context,
  /// 2048-token prefill chunks) Qwen froze the phone (RESEARCH_LOG Entry 6). One exercise needs < 1,100 tokens.
  static const _limits = {
    'max_num_sequence': 1,
    'max_total_sequence_length': 2048,
    'max_single_sequence_length': 2048,
    'prefill_chunk_size': 256,
  };

  /// Libraries are those in the engine built by tools/package_engine.sh (MLC 2024, RESEARCH_LOG Entry 7).
  /// Weights: Llama = MLC's published q4f16_0 folders; Qwen = converted by us (tools/build_phone_models.sh)
  /// from Qwen/Qwen2.5-1.5B-Instruct in both layouts: q4f16_1 = "NK", q4f16_0 = "KN".
  /// The first model is the default: the fine-tuned student model f1 (Llama-3.2-1B + LoRA, RESEARCH_LOG Entry 11),
  /// converted by notebooks/marimo/3_export/01_phone_export_f1.py. Same shape and quantization as the stock Llama-1B,
  /// so it runs on the engine's existing llama1b_q4f16_0 library.
  static const models = [
    LlmModel(
      id: 'Llama-3.2-1B-Instruct-VNeST-f1-q4f16_0',
      lib: 'llama1b_q4f16_0',
      label: 'VNeST f1 (1B)',
      size: '0.7 GB',
      engine: _limits,
    ),
    LlmModel(
      id: 'Llama-3.2-1B-Instruct-q4f16_0-MLC',
      lib: 'llama1b_q4f16_0',
      label: 'Llama-3.2-1B (untuned)',
      size: '0.7 GB',
      engine: _limits,
    ),
    LlmModel(
      id: 'Llama-3.2-3B-Instruct-q4f16_0-MLC',
      lib: 'llama3b_q4f16_0',
      label: 'Llama-3.2-3B',
      size: '1.7 GB',
      engine: _limits,
    ),
    LlmModel(
      id: 'Qwen2.5-1.5B-Instruct-q4f16_1-vnest',
      lib: 'qwen2_q4f16_1',
      label: 'Qwen-1.5B NK',
      size: '0.9 GB',
      engine: _limits,
    ),
    LlmModel(
      id: 'Qwen2.5-1.5B-Instruct-q4f16_0-vnest',
      lib: 'qwen2_q4f16_0',
      label: 'Qwen-1.5B KN',
      size: '0.9 GB',
      engine: _limits,
    ),
  ];

  LlmModel model = models.first;
  bool _restored = false;

  /// Off = the model loads but the background writer stays idle (for self-tests on a new model).
  /// On by default again: the memory limits are compiled in and every model in the engine uses the fast KN layout
  /// (RESEARCH_LOG Entry 7); it was off while Qwen NK froze the phone (Entry 6).
  bool autoWrite = true;
  void setAutoWrite(bool v) {
    autoWrite = v;
    notifyListeners();
  }

  /// Result of the last self-test, shown on the Model screen.
  String? selfTestResult;
  bool selfTestRunning = false;

  /// Small requests to measure a model: "say hello" with or without the JSON rule, or [examplePrompt] = the real
  /// ~400-token exercise prompt for "cook" (no JSON rule, 16 output tokens) to measure prompt-reading speed.
  Future<void> selfTest({required bool jsonRule, bool examplePrompt = false}) async {
    if (!isReady || selfTestRunning) return;
    final what = examplePrompt ? 'exercise prompt' : '${jsonRule ? 'with' : 'no'} JSON rule';
    selfTestRunning = true;
    selfTestResult = 'running ($what)…';
    notifyListeners();
    try {
      final r = Map<String, dynamic>.from(await _channel.invokeMethod('generateJson', {
        'system': examplePrompt ? systemPrompt : 'You are a helpful assistant.',
        'user': examplePrompt
            ? userPrompt('cook')
            : (jsonRule ? 'Reply with JSON: {"greeting": "hello"}' : 'Say hello in one short sentence.'),
        'schema': jsonRule && !examplePrompt
            ? jsonEncode({'type': 'object', 'properties': {'greeting': {'type': 'string'}}, 'required': ['greeting']})
            : '',
        'maxTokens': examplePrompt ? 16 : 24,
      }).timeout(const Duration(minutes: 3)));
      selfTestResult = '${model.label}, $what: "${r['text']}" · '
          '${r['ms']} ms · ${r['completionTokens']} tokens · ${(r['decodeTps'] as num?)?.toStringAsFixed(1)} tok/s';
    } catch (e) {
      selfTestResult = '${model.label}, $what: failed: $e';
    }
    selfTestRunning = false;
    notifyListeners();
  }

  ModelState state = ModelState.checking;
  String? modelDir;
  String? error;
  int? loadMs;

  bool get isReady => state == ModelState.ready;

  /// Switch to another model (unloads the current one first; a running exercise finishes before that).
  Future<void> select(LlmModel m) async {
    if (m.id == model.id) return;
    await unload();
    model = m;
    loadMs = null;
    error = null;
    try {
      final prefs = await SharedPreferences.getInstance();
      await prefs.setString(_modelKey, m.id);
    } catch (_) {}
    await refresh();
  }

  Future<void> refresh() async {
    if (!_restored) {
      _restored = true;
      try {
        final id = (await SharedPreferences.getInstance()).getString(_modelKey);
        model = models.firstWhere((m) => m.id == id, orElse: () => models.first);
      } catch (_) {}
    }
    try {
      final s = Map<String, dynamic>.from(await _channel.invokeMethod('status', {'modelId': model.id}));
      modelDir = s['modelDir'] as String?;
      state = s['loaded'] == true
          ? ModelState.ready
          : (s['modelPresent'] == true ? ModelState.notLoaded : ModelState.missing);
    } on PlatformException catch (e) {
      state = ModelState.error;
      error = e.message;
    } on MissingPluginException {
      state = ModelState.missing; // e.g. running on a desktop/emulator without the native side
    }
    notifyListeners();
  }

  Future<void> load() async {
    if (state == ModelState.loading || state == ModelState.ready) return;
    state = ModelState.loading;
    error = null;
    notifyListeners();
    try {
      final r = Map<String, dynamic>.from(await _channel
          .invokeMethod('load', {'modelId': model.id, 'modelLib': model.lib, 'engine': model.engine})
          // Engine errors can happen on its background thread and never answer this call (Qwen "loading" forever,
          // RESEARCH_LOG Entry 7); every model loads in < 15 s on the Note10.
          .timeout(const Duration(seconds: 60)));
      loadMs = (r['ms'] as num?)?.toInt();
      state = ModelState.ready;
    } on PlatformException catch (e) {
      state = ModelState.error;
      error = e.message;
    } on TimeoutException {
      state = ModelState.error;
      error = 'The model did not finish loading within 60 s. Close and reopen the app, then try again.';
    }
    notifyListeners();
  }

  /// Frees the model's memory and GPU. Waits for any exercise being written to finish.
  Future<void> unload() async {
    try {
      await _channel.invokeMethod('unload');
    } catch (_) {}
    state = ModelState.notLoaded;
    notifyListeners();
  }

  // ---------------- prompt ----------------

  static const _q = {
    'type': 'object',
    'properties': {
      'options': {'type': 'array', 'items': {'type': 'string'}},
      'answer': {'type': 'string'},
    },
    'required': ['options', 'answer'],
  };

  static const scenarioSchema = {
    'type': 'object',
    'properties': {'who': _q, 'what': _q, 'where': _q, 'when': _q, 'why': _q},
    'required': ['who', 'what', 'where', 'when', 'why'],
  };

  static const systemPrompt = 'You are a speech-language therapist. You write Verb Network Strengthening '
      'Treatment (VNeST) exercises for adults with aphasia. Use short, very common, concrete English words. '
      'Reply only with JSON.';

  static const _example = '{"who": {"options": ["carpenter", "wood", "cloud", "spoon"], "answer": "carpenter"}, '
      '"what": {"options": ["wood", "song", "anger", "sky"], "answer": "wood"}, '
      '"where": {"options": ["in the workshop", "under the sea", "in the sky", "on the moon"], "answer": "in the workshop"}, '
      '"when": {"options": ["before cutting", "while sleeping", "while swimming", "before he was born"], "answer": "before cutting"}, '
      '"why": {"options": ["to build a table", "to grow wings", "to make it rain", "to turn into a fish"], "answer": "to build a table"}}';

  /// [avoidPeople]: people already used for this verb, so repeated requests give different scenarios.
  static String userPrompt(String verb, {List<String> avoidPeople = const []}) =>
      'Verb: "$verb".\n'
      'Write one exercise. Each question has 4 options. ONLY ONE option may be correct; '
      'the other 3 must be clearly impossible, so a patient choosing them is definitely wrong. '
      'The answer must be copied exactly from the options.\n'
      'who: answer = a kind of person who often does this'
      '${avoidPeople.isEmpty ? '' : ' (not ${avoidPeople.join(', ')})'}. '
      'The 3 wrong options must NOT be people or animals: use objects or nature words that cannot $verb '
      '(like cloud, spoon, stone).\n'
      'what: answer = what that person ${Scenario.thirdPerson(verb)}. The 3 wrong options must be things nobody can $verb '
      '(feelings, weather, sounds, far-away things like song, anger, sky, moon).\n'
      'where, when, why: about that person and thing. Answer = the usual place, time and reason (2 to 4 words). '
      'The 3 wrong options must be impossible or silly (like under the sea, while sleeping, to grow wings).\n'
      'Example for "measure": $_example';

  // ---------------- one question per request (RESEARCH_LOG decision 2026-11-11) ----------------
  // The whole-exercise prompt above (systemPrompt / userPrompt / scenarioSchema) is kept for the
  // "Read the exercise prompt" speed test and as the record of what dataset v1 was built for.

  /// The same system line for every part. Dataset v2 (vnest_dataset/scripts) must use it word for word.
  static const partSystemPrompt = 'You write Verb Network Strengthening Treatment (VNeST) exercises for adults '
      'with aphasia. Each question has one correct answer and 3 wrong options that are clearly impossible. '
      'Use short, very common, concrete English words. '
      'Reply only with JSON: {"answer": "...", "wrong1": "...", "wrong2": "...", "wrong3": "..."}.';

  /// One question's reply: the correct answer first, then exactly 3 wrong options (fixed fields, so the model can't
  /// list too many options or leave the answer out; RESEARCH_LOG Entry 8).
  static const partSchema = {
    'type': 'object',
    'properties': {
      'answer': {'type': 'string'},
      'wrong1': {'type': 'string'},
      'wrong2': {'type': 'string'},
      'wrong3': {'type': 'string'},
    },
    'required': ['answer', 'wrong1', 'wrong2', 'wrong3'],
    'additionalProperties': false,
  };

  /// The request for one part. [done] holds the parts already written; the sentence so far is built here in code,
  /// so the model never has to write it. Each part says what the answer is and what the wrong options are, in words
  /// the model can't usefully copy as an option. Dataset v2 must build its prompts the same way.
  static String partPrompt(String verb, QKind k, Map<QKind, Question> done, {List<String> avoidPeople = const []}) {
    final v3 = Scenario.thirdPerson(verb);
    String a(QKind q) => Scenario.noun(done[q]!.answer);
    final head = 'VNeST "$verb". ${k.name}?';
    return switch (k) {
      QKind.who => '$head Answer: a person (1 or 2 words) who often $v3 things. Wrong: 3 things that cannot $verb.'
          '${avoidPeople.isEmpty ? '' : ' The answer must not be: ${avoidPeople.join(', ')}.'}',
      QKind.what => '$head The ${a(QKind.who)} $v3 ___. Answer: what the ${a(QKind.who)} $v3. '
          'Wrong: 3 things nobody can $verb.',
      QKind.where => '$head The ${a(QKind.who)} $v3 the ${a(QKind.what)} ___. '
          'Answer: the usual place (2 to 4 words). Wrong: 3 impossible places.',
      QKind.when => '$head The ${a(QKind.who)} $v3 the ${a(QKind.what)} ${done[QKind.where]!.answer} ___. '
          'Answer: the usual time (2 to 4 words). Wrong: 3 impossible times.',
      QKind.why => '$head The ${a(QKind.who)} $v3 the ${a(QKind.what)} ${done[QKind.where]!.answer} '
          '${done[QKind.when]!.answer} ___. Answer: the usual reason, starting with "to" (2 to 5 words). '
          'Wrong: 3 silly reasons.',
    };
  }

  static const partTries = 3; // first try + 2 retries, per part
  static const _partMaxTokens = 48; // one question is ~25 tokens in the fixed-field shape

  /// Writes one exercise for [verb], ONE QUESTION PER REQUEST: who, what, where, when, why, each request given the
  /// parts already written. A part that fails its checks is redone on its own (up to [partTries] times).
  /// [onPart] is called as soon as a part passes, so a session can start on "who" while "what" is being written.
  /// [keepGoing] is checked before every request; returning false stops (e.g. the patient opened another verb).
  Future<ScenarioResult> generateScenario(
    String verb, {
    List<String> avoidPeople = const [],
    void Function(QKind kind, Question q)? onPart,
    bool Function()? keepGoing,
  }) async {
    if (!isReady) return const ScenarioResult(rejectedReason: 'model not loaded');
    final label = model.label;
    final done = <QKind, Question>{};
    final raw = StringBuffer();
    var ms = 0, tokens = 0;
    double? tps;
    ScenarioResult fail(String why) =>
        ScenarioResult(rejectedReason: why, rawText: raw.toString(), ms: ms, tokens: tokens, tps: tps, model: label);

    for (final k in QKind.values) {
      String? lastError;
      for (var t = 0; t < partTries && !done.containsKey(k); t++) {
        if (keepGoing != null && !keepGoing()) return fail('stopped');
        if (!isReady) return fail('model not loaded');
        final Map<String, dynamic> r;
        try {
          r = Map<String, dynamic>.from(await _channel.invokeMethod('generateJson', {
            'system': partSystemPrompt,
            'user': partPrompt(verb, k, done, avoidPeople: avoidPeople),
            'schema': jsonEncode(partSchema),
            'maxTokens': _partMaxTokens,
          }).timeout(const Duration(minutes: 2)));
        } catch (e) {
          return fail('model error at ${k.name}: $e');
        }
        final text = r['text'] as String? ?? '';
        ms += (r['ms'] as num?)?.toInt() ?? 0;
        tokens += (r['completionTokens'] as num?)?.toInt() ?? 0;
        tps = (r['decodeTps'] as num?)?.toDouble() ?? tps;
        raw.writeln('${k.name}: $text');
        try {
          final decoded = jsonDecode(text);
          if (decoded is! Map) throw FormatException('${k.name}: not a JSON object');
          final q = Scenario.partFromModel(k, decoded);
          Scenario.checkContent(k, q, verb: verb);
          if (k == QKind.who && avoidPeople.contains(Scenario.noun(q.answer))) {
            throw FormatException('who: "${q.answer}" was already used for "$verb"');
          }
          if (k == QKind.what) Scenario.checkWhoWhat(done[QKind.who]!, q);
          done[k] = q;
          onPart?.call(k, q);
        } on FormatException catch (e) {
          lastError = e.message;
        }
      }
      if (!done.containsKey(k)) return fail('${lastError ?? k.name} (after $partTries tries)');
    }
    final s = Scenario(verb: verb, questions: done, source: ScenarioSource.llm, ms: ms, tokens: tokens);
    return ScenarioResult(scenario: s, rawText: raw.toString(), ms: ms, tokens: tokens, tps: tps, model: label);
  }
}
