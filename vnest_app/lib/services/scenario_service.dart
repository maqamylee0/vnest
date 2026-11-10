import 'dart:convert';

import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../data/scenario.dart';
import '../data/verb_network.dart';
import '../logic/exercise_builder.dart';
import 'llm_service.dart';

enum VerbStatus { ready, writing, reviewedOnly, waitingForModel, failed }

/// Verbs (standing in for the therapist's backend) and the exercises written for them.
///
/// When the model is ready, a background loop asks it for scenarios, one at a time,
/// until every verb has [target]. Finished scenarios are stored on the phone, so
/// practice never waits for the model.
class ScenarioService extends ChangeNotifier {
  ScenarioService(this.llm, this.curated) {
    llm.addListener(_onModelChanged);
  }

  final LlmService llm;
  final VerbRepository curated; // reviewed lists for the original verbs (fallback only)

  static const target = 3;
  static const _addedKey = 'added_verbs_v1';
  String _key(String verb) => 'scenarios_v1:$verb';

  List<String> verbs = [];
  Set<String> _curatedVerbs = {};
  final Map<String, List<Scenario>> _scenarios = {};
  final Map<String, String> lastError = {};
  String? writingVerb;
  bool _running = false;
  bool stopping = false; // Stop pressed: finish the current exercise, then unload

  /// Stop writing and free the phone (the current exercise finishes first, up to ~2 min).
  Future<void> stop() async {
    stopping = true;
    notifyListeners();
    await llm.unload(); // waits on the native lock until the current exercise is done
    stopping = false;
    notifyListeners();
  }

  Future<void> start() async {
    stopping = false;
    await llm.load();
  }
  final List<ScenarioResult> log = []; // most recent first, for the helper screen

  Future<void> init() async {
    final raw = jsonDecode(await rootBundle.loadString('assets/therapist_verbs.json')) as Map<String, dynamic>;
    final prefs = await SharedPreferences.getInstance();
    verbs = {
      for (final v in raw['verbs'] as List) v as String,
      ...prefs.getStringList(_addedKey) ?? const <String>[],
    }.toList();
    _curatedVerbs = {for (final n in await curated.load()) n.verb};
    for (final v in verbs) {
      _scenarios[v] = [for (final s in prefs.getStringList(_key(v)) ?? const <String>[]) Scenario.fromJson(jsonDecode(s))];
    }
    notifyListeners();
    _pump();
  }

  List<Scenario> modelScenarios(String verb) => _scenarios[verb] ?? const [];

  VerbStatus status(String verb) {
    if (writingVerb == verb) return VerbStatus.writing;
    if (modelScenarios(verb).isNotEmpty) return VerbStatus.ready;
    if (lastError.containsKey(verb) && llm.isReady) return VerbStatus.failed;
    return _curatedVerbs.contains(verb) ? VerbStatus.reviewedOnly : VerbStatus.waitingForModel;
  }

  /// Scenarios for a session: the model's if there are any, otherwise built from the
  /// reviewed word lists (original 8 verbs only). Empty = nothing to practise yet.
  Future<List<Scenario>> forSession(String verb) async {
    final fromModel = [...modelScenarios(verb)]..shuffle();
    if (fromModel.isNotEmpty) return fromModel.take(target).toList();
    final networks = await curated.load();
    final net = networks.where((n) => n.verb == verb).firstOrNull;
    if (net == null) return const [];
    return _curatedScenarios(net, networks);
  }

  Future<String?> addVerb(String input) async {
    final verb = input.trim().toLowerCase();
    if (!RegExp(r'^[a-z]{2,20}$').hasMatch(verb)) return 'Type one English verb, letters only (e.g. "wash").';
    if (verbs.contains(verb)) return '"$verb" is already in the list.';
    verbs.add(verb);
    _scenarios[verb] = [];
    final prefs = await SharedPreferences.getInstance();
    await prefs.setStringList(_addedKey, [...prefs.getStringList(_addedKey) ?? const <String>[], verb]);
    notifyListeners();
    _pump();
    return null;
  }

  /// Delete everything the model wrote (to re-test a new prompt).
  Future<void> clearGenerated() async {
    final prefs = await SharedPreferences.getInstance();
    for (final v in verbs) {
      await prefs.remove(_key(v));
      _scenarios[v] = [];
    }
    lastError.clear();
    log.clear();
    notifyListeners();
    _pump();
  }

  void _onModelChanged() {
    notifyListeners();
    _pump();
  }

  /// Background writer: one scenario at a time while the model is ready.
  Future<void> _pump() async {
    if (_running || !llm.isReady || stopping) return;
    _running = true;
    try {
      while (llm.isReady && !stopping) {
        // Least-covered verb first, skipping verbs that failed 3 times in a row.
        final todo = verbs.where((v) => modelScenarios(v).length < target && (_failures[v] ?? 0) < 3).toList()
          ..sort((a, b) => modelScenarios(a).length.compareTo(modelScenarios(b).length));
        if (todo.isEmpty) break;
        final verb = todo.first;
        writingVerb = verb;
        notifyListeners();
        final result = await llm.generateScenario(verb, avoidPeople: [for (final s in modelScenarios(verb)) s.agent]);
        log.insert(0, result);
        if (log.length > 20) log.removeLast();
        if (result.scenario != null) {
          await _save(verb, result.scenario!);
          lastError.remove(verb);
          _failures.remove(verb);
        } else {
          lastError[verb] = result.rejectedReason ?? 'unknown error';
          _failures[verb] = (_failures[verb] ?? 0) + 1;
        }
        writingVerb = null;
        notifyListeners();
      }
    } finally {
      writingVerb = null;
      _running = false;
      notifyListeners();
    }
  }

  final Map<String, int> _failures = {};

  Future<void> _save(String verb, Scenario s) async {
    final list = _scenarios.putIfAbsent(verb, () => [])..add(s);
    final prefs = await SharedPreferences.getInstance();
    await prefs.setStringList(_key(verb), [for (final x in list) jsonEncode(x.toJson())]);
  }

  // ---------- fallback: scenarios from the reviewed word lists ----------
  static const _absurd = {
    QKind.where: ['under the sea', 'in the sky', 'on the moon', 'inside a cloud'],
    QKind.when: ['while sleeping', 'while swimming', 'before he was born', 'during a dream'],
    QKind.why: ['to grow wings', 'to make it rain', 'to turn into a fish', 'to stop the sun'],
  };

  List<Scenario> _curatedScenarios(VerbNetwork net, List<VerbNetwork> all) {
    final b = ExerciseBuilder(all);
    final pair = net.pairs.first; // the only pair with reviewed where/when/why
    final who = b.whoRound(net, pair);
    final what = b.whatRound(net, pair);
    Question wh(QKind k) {
      final answer = net.wh[WhKind.values[k.index - 2]];
      final wrong = [..._absurd[k]!]..shuffle(); // copy: the lists are const
      return Question([answer, ...wrong.take(3)]..shuffle(), answer);
    }

    return [
      Scenario(
        verb: net.verb,
        source: ScenarioSource.curated,
        questions: {
          QKind.who: Question([for (final o in who) o.word], pair.agent),
          QKind.what: Question([for (final o in what) o.word], pair.patient),
          QKind.where: wh(QKind.where),
          QKind.when: wh(QKind.when),
          QKind.why: wh(QKind.why),
        },
      ),
    ];
  }
}
