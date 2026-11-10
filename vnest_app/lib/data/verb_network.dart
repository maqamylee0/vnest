import 'dart:convert';

import 'package:flutter/services.dart';

/// One (who, what) pair, e.g. chef / soup.
class Pair {
  const Pair(this.agent, this.patient);
  final String agent;
  final String patient;

  @override
  bool operator ==(Object other) => other is Pair && other.agent == agent && other.patient == patient;
  @override
  int get hashCode => Object.hash(agent, patient);
  @override
  String toString() => '$agent / $patient';
}

/// Where/when/why answers for one sentence.
class WhAnswers {
  const WhAnswers({required this.where, required this.when, required this.why});
  final String where;
  final String when;
  final String why;

  factory WhAnswers.fromJson(Map<String, dynamic> j) =>
      WhAnswers(where: j['where'] as String, when: j['when'] as String, why: j['why'] as String);
  Map<String, String> toJson() => {'where': where, 'when': when, 'why': why};

  String operator [](WhKind k) => switch (k) { WhKind.where => where, WhKind.when => when, WhKind.why => why };
}

enum WhKind { where, when, why }

/// A clinician-curated verb network: the correct pairs for a verb, plus
/// other objects that would also be correct (so they're never used as distractors).
class VerbNetwork {
  const VerbNetwork({
    required this.verb,
    required this.verb3,
    required this.pairs,
    required this.alsoValid,
    required this.wh,
    this.notWrongAgents = const {},
  });

  final String verb; // cook
  final String verb3; // cooks  (for "The chef cooks the soup.")
  final List<Pair> pairs;
  final Set<String> alsoValid;
  final WhAnswers wh; // reviewed answers for pairs.first

  /// Things that could sound like they do this action ("the bus drives", "plants drink water"),
  /// so they are never offered as a wrong answer to "Who ...?".
  final Set<String> notWrongAgents;

  Set<String> get validPatients => {...pairs.map((p) => p.patient), ...alsoValid};
  Set<String> get validAgents => pairs.map((p) => p.agent).toSet();

  factory VerbNetwork.fromJson(Map<String, dynamic> j) => VerbNetwork(
        verb: j['verb'] as String,
        verb3: j['verb3'] as String,
        pairs: [for (final p in j['pairs'] as List) Pair(p[0] as String, p[1] as String)],
        alsoValid: {for (final s in j['also_valid'] as List) s as String},
        wh: WhAnswers.fromJson(j['wh'] as Map<String, dynamic>),
        notWrongAgents: {for (final s in (j['not_wrong_agents'] as List? ?? const [])) s as String},
      );
}

class VerbRepository {
  List<VerbNetwork>? _cache;

  Future<List<VerbNetwork>> load() async {
    if (_cache != null) return _cache!;
    final raw = await rootBundle.loadString('assets/verb_networks.json');
    final j = jsonDecode(raw) as Map<String, dynamic>;
    return _cache = [for (final v in j['verbs'] as List) VerbNetwork.fromJson(v as Map<String, dynamic>)];
  }
}
