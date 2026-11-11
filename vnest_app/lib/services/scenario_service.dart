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

  /// The exercise being written right now, filled in one question at a time (who, what, where, when, why).
  Scenario? draft;
  Scenario? _pendingLive; // created by startLive() before the writer picks the verb up
  String? _priority; // verb a patient is waiting for: written next, and the current exercise stops for it
  /// Live exercises that failed (a session showing one tells the patient and offers to go back).
  final Set<Scenario> failedLive = {};
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

  /// A patient opened [verb] and no written exercise is stored: write one now, question by question, and return it.
  /// The session shows each question as soon as it is written ([draft] fills in); if the writer is busy with another
  /// verb, it stops that one at the next question and switches. Check [failedLive] for a failure.
  Scenario startLive(String verb) {
    _priority = verb;
    _failures.remove(verb); // a patient is waiting: always try again, even if background writing gave up on it
    if (draft != null && draft!.verb == verb) return draft!;
    final live = _pendingLive?.verb == verb
        ? _pendingLive!
        : Scenario(verb: verb, questions: {}, source: ScenarioSource.llm);
    _pendingLive = live;
    _pump();
    return live;
  }

  String? _nextVerb() {
    if (_priority != null && (_failures[_priority] ?? 0) < 3) return _priority;
    // Least-covered verb first, skipping verbs that failed 3 times in a row.
    final todo = verbs.where((v) => modelScenarios(v).length < target && (_failures[v] ?? 0) < 3).toList()
      ..sort((a, b) => modelScenarios(a).length.compareTo(modelScenarios(b).length));
    return todo.firstOrNull;
  }

  /// Background writer: one exercise at a time, one question per request, while the model is ready.
  Future<void> _pump() async {
    if (_running || !llm.isReady || stopping || !(llm.autoWrite || _priority != null)) return;
    _running = true;
    try {
      while (llm.isReady && !stopping && (llm.autoWrite || _priority != null)) {
        final verb = _nextVerb();
        if (verb == null) break;
        final d = _pendingLive?.verb == verb ? _pendingLive! : Scenario(verb: verb, questions: {}, source: ScenarioSource.llm);
        if (identical(d, _pendingLive)) _pendingLive = null;
        final isLive = verb == _priority;
        draft = d;
        writingVerb = verb;
        notifyListeners();
        final result = await llm.generateScenario(
          verb,
          avoidPeople: [for (final s in modelScenarios(verb)) s.agent],
          onPart: (k, q) {
            d.questions[k] = q;
            notifyListeners();
          },
          // Stop between questions if writing was switched off/stopped, or a patient is waiting for another verb.
          keepGoing: () => !stopping && (llm.autoWrite || _priority == verb) && (_priority == null || _priority == verb),
        );
        draft = null;
        writingVerb = null;
        if (result.rejectedReason == 'stopped') {
          if (isLive) failedLive.add(d); // only if the patient left it for another verb; nobody is waiting on it
          notifyListeners();
          continue; // switched to another verb: not a failure of the model
        }
        log.insert(0, result);
        if (log.length > 20) log.removeLast();
        if (result.scenario != null) {
          await _save(verb, result.scenario!);
          lastError.remove(verb);
          _failures.remove(verb);
        } else {
          lastError[verb] = result.rejectedReason ?? 'unknown error';
          _failures[verb] = (_failures[verb] ?? 0) + 1;
          if (isLive) failedLive.add(d);
        }
        if (_priority == verb) _priority = null;
        notifyListeners();
      }
    } finally {
      draft = null;
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
