import 'dart:convert';

import 'package:shared_preferences/shared_preferences.dart';

enum PracticeStep { pairs, questions, sentences }

/// One answered item. Stored on the phone only.
class Attempt {
  Attempt({
    required this.verb,
    required this.step,
    required this.firstTry,
    required this.tries,
    required this.ms,
    required this.at,
    this.fromModel = false,
  });
  final String verb;
  final PracticeStep step;
  final bool firstTry; // correct on the first tap
  final int tries; // taps until correct (1 = first try)
  final int ms; // time to correct answer
  final DateTime at;
  final bool fromModel; // the answer options came from the on-device model

  Map<String, dynamic> toJson() => {
        'verb': verb, 'step': step.name, 'firstTry': firstTry, 'tries': tries, 'ms': ms,
        'at': at.toIso8601String(), 'fromModel': fromModel,
      };
  factory Attempt.fromJson(Map<String, dynamic> j) => Attempt(
        verb: j['verb'] as String,
        step: PracticeStep.values.byName(j['step'] as String),
        firstTry: j['firstTry'] as bool,
        tries: j['tries'] as int,
        ms: j['ms'] as int,
        at: DateTime.parse(j['at'] as String),
        fromModel: j['fromModel'] as bool? ?? false,
      );
}

class StepStats {
  const StepStats(this.attempts, this.firstTry);
  final int attempts;
  final int firstTry;
  int? get pct => attempts == 0 ? null : (100 * firstTry / attempts).round();
}

class ProgressSummary {
  ProgressSummary({
    required this.sessions,
    required this.thisWeek,
    required this.lastWeek,
    required this.byStep,
    required this.needsPractice,
    required this.medianSeconds,
  });
  final int sessions;
  final StepStats thisWeek;
  final StepStats lastWeek;
  final Map<PracticeStep, StepStats> byStep; // this week
  final List<String> needsPractice; // verbs < 60% first-try this week (>= 4 items)
  final double? medianSeconds;
}

/// Progress is computed with plain code: exact, instant, and auditable by clinicians.
class ProgressStore {
  static const _attemptsKey = 'attempts_v1';
  static const _sessionsKey = 'sessions_v1';

  Future<void> record(Attempt a) async {
    final prefs = await SharedPreferences.getInstance();
    final list = prefs.getStringList(_attemptsKey) ?? [];
    list.add(jsonEncode(a.toJson()));
    await prefs.setStringList(_attemptsKey, list);
  }

  Future<void> sessionCompleted() async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setInt(_sessionsKey, (prefs.getInt(_sessionsKey) ?? 0) + 1);
  }

  Future<List<Attempt>> all() async {
    final prefs = await SharedPreferences.getInstance();
    return [for (final s in prefs.getStringList(_attemptsKey) ?? []) Attempt.fromJson(jsonDecode(s))];
  }

  Future<ProgressSummary> summary({DateTime? now}) async {
    final prefs = await SharedPreferences.getInstance();
    final attempts = await all();
    now ??= DateTime.now();
    final weekAgo = now.subtract(const Duration(days: 7));
    final twoWeeksAgo = now.subtract(const Duration(days: 14));
    final thisWeek = attempts.where((a) => a.at.isAfter(weekAgo)).toList();
    final lastWeek = attempts.where((a) => a.at.isAfter(twoWeeksAgo) && !a.at.isAfter(weekAgo)).toList();

    StepStats stats(Iterable<Attempt> xs) => StepStats(xs.length, xs.where((a) => a.firstTry).length);

    final byVerb = <String, List<Attempt>>{};
    for (final a in thisWeek) {
      byVerb.putIfAbsent(a.verb, () => []).add(a);
    }
    final needs = [
      for (final e in byVerb.entries)
        if (e.value.length >= 4 && (stats(e.value).pct ?? 100) < 60) e.key,
    ]..sort();

    final secs = thisWeek.map((a) => a.ms / 1000).toList()..sort();
    return ProgressSummary(
      sessions: prefs.getInt(_sessionsKey) ?? 0,
      thisWeek: stats(thisWeek),
      lastWeek: stats(lastWeek),
      byStep: {for (final s in PracticeStep.values) s: stats(thisWeek.where((a) => a.step == s))},
      needsPractice: needs,
      medianSeconds: secs.isEmpty ? null : secs[secs.length ~/ 2],
    );
  }

  Future<void> clear() async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.remove(_attemptsKey);
    await prefs.remove(_sessionsKey);
  }
}
