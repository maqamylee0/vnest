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
  const LlmModel({required this.id, required this.lib, required this.label, required this.size});
  final String id; // weights folder under the app's external files dir
  final String lib;
  final String label;
  final String size; // shown in the copy-over-USB instructions
}

/// Runs an on-device LLM (via LlmChannel.kt / MLC LLM). The model plays the
/// therapist: for a verb, it writes the five questions with 4 options each and marks the
/// correct answer. The app's code then checks the patient's taps against that answer.
class LlmService extends ChangeNotifier {
  static const _channel = MethodChannel('vnest/llm');
  static const _modelKey = 'llm_model_v1';

  static const models = [
    LlmModel(
      id: 'Llama-3.2-3B-Instruct-q4f16_0-MLC',
      lib: 'llama_q4f16_0_2d32572d8a4ab2af20a1f587ef6c8c63',
      label: 'Llama-3.2-3B',
      size: '1.7 GB',
    ),
    LlmModel(
      id: 'Qwen2.5-1.5B-Instruct-q4f16_1-MLC',
      lib: 'qwen2_q4f16_1_2e221f430380225c03990ad24c3d030e',
      label: 'Qwen2.5-1.5B',
      size: '0.9 GB',
    ),
  ];

  LlmModel model = models.first;
  bool _restored = false;

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
      final r = Map<String, dynamic>.from(await _channel.invokeMethod('load', {'modelId': model.id, 'modelLib': model.lib}));
      loadMs = (r['ms'] as num?)?.toInt();
      state = ModelState.ready;
    } on PlatformException catch (e) {
      state = ModelState.error;
      error = e.message;
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

  /// Asks the model for one scenario for [verb]. Takes ~1.5-2 minutes on a Galaxy Note 10.
  Future<ScenarioResult> generateScenario(String verb, {List<String> avoidPeople = const []}) async {
    if (!isReady) return const ScenarioResult(rejectedReason: 'model not loaded');
    final label = model.label;
    Map<String, dynamic> r;
    try {
      r = Map<String, dynamic>.from(await _channel.invokeMethod('generateJson', {
        'system': systemPrompt,
        'user': userPrompt(verb, avoidPeople: avoidPeople),
        'schema': jsonEncode(scenarioSchema),
        'maxTokens': 320,
      }).timeout(const Duration(minutes: 5)));
    } catch (e) {
      return ScenarioResult(rejectedReason: 'model error: $e', model: label);
    }
    final text = r['text'] as String? ?? '';
    final ms = (r['ms'] as num?)?.toInt();
    final tokens = (r['completionTokens'] as num?)?.toInt();
    final tps = (r['decodeTps'] as num?)?.toDouble();
    try {
      final s = Scenario.fromModel(verb, jsonDecode(text) as Map<String, dynamic>, ms: ms, tokens: tokens);
      return ScenarioResult(scenario: s, rawText: text, ms: ms, tokens: tokens, tps: tps, model: label);
    } on FormatException catch (e) {
      return ScenarioResult(rejectedReason: e.message, rawText: text, ms: ms, tokens: tokens, tps: tps, model: label);
    }
  }
}
