import 'dart:math';

import '../data/verb_network.dart';

/// Why a choice is wrong. For clinicians and tests, not shown to patients.
enum DistractorKind {
  roleSwap, // an object offered as the "who" (soup cooks), or a swapped sentence
  notAnAgent, // another verb's object offered as the "who" (pipe cooks)
  wrongObject, // an object that can't take this verb (the chef cooks the car)
}

/// One word on a choice button.
class WordOption {
  const WordOption(this.word, {this.kind});
  final String word;
  final DistractorKind? kind; // null = correct
  bool get isCorrect => kind == null;
}

class SentenceItem {
  const SentenceItem(this.text, this.makesSense, {this.kind});
  final String text;
  final bool makesSense;
  final DistractorKind? kind;
}

/// Builds every multiple-choice item from curated content. No language model involved,
/// so every "correct" answer is one a clinician listed, and every distractor is checked
/// against the verb's full list of valid objects.
class ExerciseBuilder {
  ExerciseBuilder(this.all, {Random? rng}) : _rng = rng ?? Random();
  final List<VerbNetwork> all;
  final Random _rng;

  /// Objects from OTHER verbs that are not valid for [v].
  /// e.g. for "cook": pipe, tractor, roses… but not "rice" or "maize" (listed as valid).
  List<String> wrongObjectsFor(VerbNetwork v) {
    final valid = v.validPatients;
    return {
      for (final other in all)
        if (other.verb != v.verb)
          for (final p in other.pairs)
            if (!valid.contains(p.patient)) p.patient,
    }.toList();
  }

  /// Step 1a, "Who cooks?": the right person + 3 things that can't do the action.
  ///  - one of this verb's own objects ("soup"): tests telling who from what, as in VNeST
  ///  - two objects from other verbs ("pipe", "guitar")
  /// Never another person: almost anyone can cook, so "plumber" would also be right.
  List<WordOption> whoRound(VerbNetwork v, Pair target) {
    bool usable(String w) => !v.validAgents.contains(w) && !v.notWrongAgents.contains(w) && w != target.agent;
    final own = v.pairs.map((p) => p.patient).where(usable).toList()..shuffle(_rng);
    final others = {
      for (final o in all)
        if (o.verb != v.verb)
          for (final p in o.pairs)
            if (usable(p.patient) && !own.contains(p.patient)) p.patient,
    }.toList()
      ..shuffle(_rng);
    final picks = <WordOption>[
      if (own.isNotEmpty) WordOption(own.first, kind: DistractorKind.roleSwap),
      for (final w in others) WordOption(w, kind: DistractorKind.notAnAgent),
    ].take(3);
    return [WordOption(target.agent), ...picks]..shuffle(_rng);
  }

  /// Step 1b, "What does the chef cook?": the right object + 3 objects that are
  /// never valid for this verb (checked against pairs + also_valid).
  List<WordOption> whatRound(VerbNetwork v, Pair target) {
    final wrong = wrongObjectsFor(v)..shuffle(_rng);
    return [
      WordOption(target.patient),
      for (final w in wrong.take(3)) WordOption(w, kind: DistractorKind.wrongObject),
    ]..shuffle(_rng);
  }

  static String whoQuestion(VerbNetwork v) => 'Who ${v.verb3}?';
  static String whatQuestion(VerbNetwork v, String agent) => 'What does the $agent ${v.verb}?';

  /// Step 3: "Does this make sense?" — 2 correct sentences, 1 role swap, 1 wrong object.
  List<SentenceItem> sentenceRound(VerbNetwork v) {
    final pairs = [...v.pairs]..shuffle(_rng);
    final wrongObjects = wrongObjectsFor(v)..shuffle(_rng);
    final items = [
      SentenceItem(sentence(v, pairs[0]), true),
      SentenceItem(sentence(v, pairs[1]), true),
      SentenceItem(sentence(v, Pair(pairs[2].patient, pairs[2].agent)), false, kind: DistractorKind.roleSwap),
      SentenceItem(sentence(v, Pair(pairs[3].agent, wrongObjects[0])), false, kind: DistractorKind.wrongObject),
    ];
    return items..shuffle(_rng);
  }

  // Step 2 (where/when/why) is deliberately NOT multiple choice: many answers are right
  // ("in the morning" fits most actions), so borrowed distractors would often be correct.
  // The session shows it as an open question with the model's answer as an example.

  static String sentence(VerbNetwork v, Pair p) => 'The ${p.agent} ${v.verb3} the ${p.patient}.';

  static String question(WhKind k, VerbNetwork v, Pair p) => switch (k) {
        WhKind.where => 'Where does the ${p.agent} ${v.verb} the ${p.patient}?',
        WhKind.when => 'When does the ${p.agent} ${v.verb} the ${p.patient}?',
        WhKind.why => 'Why does the ${p.agent} ${v.verb} the ${p.patient}?',
      };
}
