import 'dart:math';

/// The five questions in one VNeST scenario, in the order they're asked.
enum QKind { who, what, where, when, why }

/// One multiple-choice question: options + the correct answer (one of the options).
class Question {
  const Question(this.options, this.answer);
  final List<String> options;
  final String answer;

  bool isCorrect(String choice) => choice == answer;

  Map<String, dynamic> toJson() => {'options': options, 'answer': answer};
  factory Question.fromJson(Map<String, dynamic> j) =>
      Question([for (final o in j['options'] as List) o as String], j['answer'] as String);
}

enum ScenarioSource { llm, curated }

/// One exercise for a verb: "Who cooks?" → chef, "What does the chef cook?" → soup,
/// then where / when / why about "the chef cooks the soup".
/// The model writes the options and marks the answer; the app's code checks the patient's taps.
class Scenario {
  Scenario({
    required this.verb,
    required this.questions,
    required this.source,
    this.ms,
    this.tokens,
  });

  final String verb;
  final Map<QKind, Question> questions;
  final ScenarioSource source;
  final int? ms; // generation time on the phone
  final int? tokens;

  String get verb3 => thirdPerson(verb);
  String get agent => noun(questions[QKind.who]!.answer);
  String get patient => noun(questions[QKind.what]!.answer);

  /// True once all five questions are there (an exercise being written part by part is incomplete).
  bool get isComplete => QKind.values.every(questions.containsKey);

  String prompt(QKind k) => switch (k) {
        QKind.who => 'Who $verb3?',
        QKind.what => 'What does the $agent $verb?',
        QKind.where => 'Where does the $agent $verb the $patient?',
        QKind.when => 'When does the $agent $verb the $patient?',
        QKind.why => 'Why does the $agent $verb the $patient?',
      };

  String get sentence => 'The $agent $verb3 the $patient.';

  Map<String, dynamic> toJson() => {
        'verb': verb,
        'source': source.name,
        if (ms != null) 'ms': ms,
        if (tokens != null) 'tokens': tokens,
        'questions': {for (final e in questions.entries) e.key.name: e.value.toJson()},
      };

  factory Scenario.fromJson(Map<String, dynamic> j) => Scenario(
        verb: j['verb'] as String,
        source: ScenarioSource.values.byName(j['source'] as String),
        ms: j['ms'] as int?,
        tokens: j['tokens'] as int?,
        questions: {
          for (final k in QKind.values) k: Question.fromJson((j['questions'] as Map)[k.name] as Map<String, dynamic>),
        },
      );

  /// Builds a scenario from the model's JSON, or throws [FormatException] saying why it can't be used.
  /// Light checks only (this is a test build): 4 distinct short options, answer is one of them.
  factory Scenario.fromModel(String verb, Map<String, dynamic> j, {int? ms, int? tokens, Random? rng}) {
    final qs = <QKind, Question>{};
    for (final k in QKind.values) {
      final raw = j[k.name];
      if (raw is! Map) throw FormatException('missing "${k.name}"');
      qs[k] = partFromModel(k, raw, rng: rng);
    }
    checkWhoWhat(qs[QKind.who]!, qs[QKind.what]!);
    return Scenario(verb: verb, questions: qs, source: ScenarioSource.llm, ms: ms, tokens: tokens);
  }

  /// Checks ONE question as written by the model ({"options": [...], "answer": "..."}), or throws [FormatException]:
  /// 4 distinct options of at most 6 words, the answer is one of them. Used per part when exercises are
  /// written one question per request (RESEARCH_LOG decision 2026-11-11), and by [Scenario.fromModel].
  ///
  /// Two reply shapes are accepted: the per-part shape {"answer", "wrong1", "wrong2", "wrong3"} (exactly 4 options by
  /// construction, answer always among them; RESEARCH_LOG Entry 8) and the older {"options": [...], "answer"}.
  static Question partFromModel(QKind k, Map raw, {Random? rng}) {
    final answer = clean(raw['answer']?.toString() ?? '');
    final options = <String>[];
    final listed = raw.containsKey('wrong1')
        ? [raw['answer'], raw['wrong1'], raw['wrong2'], raw['wrong3']]
        : (raw['options'] as List? ?? const []);
    for (final o in listed) {
      if (o == null) continue;
      final c = clean(o.toString());
      if (c.isNotEmpty && !options.contains(c)) options.add(c);
    }
    if (answer.isEmpty) throw FormatException('${k.name}: empty answer');
    if (!options.contains(answer)) throw FormatException('${k.name}: answer "$answer" is not one of the options');
    final wrong = options.where((o) => o != answer).toList();
    if (wrong.length < 3) throw FormatException('${k.name}: fewer than 4 different options');
    final picked = [answer, ...wrong.take(3)];
    for (final o in picked) {
      if (o.split(' ').length > 6) throw FormatException('${k.name}: option too long: "$o"');
    }
    return Question(picked..shuffle(rng ?? Random()), answer); // the model tends to put the answer first
  }

  /// The person and the thing must differ ("who cooks?" → chef, "what does the chef cook?" → not chef).
  static void checkWhoWhat(Question who, Question what) {
    if (noun(who.answer) == noun(what.answer)) throw const FormatException('who and what are the same');
  }

  static String clean(String s) =>
      s.trim().replaceAll(RegExp(r'[.!?]+$'), '').replaceAll(RegExp(r'\s+'), ' ').toLowerCase();

  /// "a chef" -> "chef", "the egg" -> "egg", so sentences read "The chef cooks the egg", not "The a chef".
  static String noun(String s) => s.replaceFirst(RegExp(r'^(a|an|the)\s+'), '');

  /// cook -> cooks, fix -> fixes, carry -> carries, go -> goes.
  static String thirdPerson(String verb) {
    const irregular = {'have': 'has', 'be': 'is', 'go': 'goes', 'do': 'does'};
    if (irregular.containsKey(verb)) return irregular[verb]!;
    if (RegExp(r'(s|x|z|ch|sh|o)$').hasMatch(verb)) return '${verb}es';
    if (RegExp(r'[^aeiou]y$').hasMatch(verb)) return '${verb.substring(0, verb.length - 1)}ies';
    return '${verb}s';
  }
}
