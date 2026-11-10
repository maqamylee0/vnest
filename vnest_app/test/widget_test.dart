import 'dart:convert';
import 'dart:io';
import 'dart:math';

import 'package:flutter_test/flutter_test.dart';
import 'package:vnest_app/data/scenario.dart';
import 'package:vnest_app/data/verb_network.dart';
import 'package:vnest_app/logic/exercise_builder.dart';
import 'package:vnest_app/services/llm_service.dart';

List<VerbNetwork> loadVerbs() {
  final j = jsonDecode(File('assets/verb_networks.json').readAsStringSync()) as Map<String, dynamic>;
  return [for (final v in j['verbs'] as List) VerbNetwork.fromJson(v as Map<String, dynamic>)];
}

void main() {
  final verbs = loadVerbs();

  test('content: every verb has 6 pairs and reviewed wh answers', () {
    for (final v in verbs) {
      expect(v.pairs.length, 6, reason: v.verb);
      expect(v.pairs.toSet().length, 6, reason: '${v.verb} has duplicate pairs');
      expect([v.wh.where, v.wh.when, v.wh.why].every((s) => s.isNotEmpty), isTrue);
    }
  });

  test('who rounds: one right person, 3 non-agents, never a listed "could do it" thing', () {
    for (var seed = 0; seed < 200; seed++) {
      final b = ExerciseBuilder(verbs, rng: Random(seed));
      for (final v in verbs) {
        for (final p in v.pairs) {
          final opts = b.whoRound(v, p);
          expect(opts.length, 4);
          expect(opts.where((o) => o.isCorrect).single.word, p.agent);
          expect(opts.map((o) => o.word).toSet().length, 4, reason: 'duplicate words for ${v.verb}');
          for (final o in opts.where((o) => !o.isCorrect)) {
            expect(v.validAgents.contains(o.word), isFalse, reason: '${v.verb}: "${o.word}" is a valid agent');
            expect(v.notWrongAgents.contains(o.word), isFalse, reason: '${v.verb}: "${o.word}" could do the action');
          }
        }
      }
    }
  });

  test('what rounds: one right object, and no wrong choice is valid for the verb', () {
    for (var seed = 0; seed < 200; seed++) {
      final b = ExerciseBuilder(verbs, rng: Random(seed));
      for (final v in verbs) {
        for (final p in v.pairs) {
          final opts = b.whatRound(v, p);
          expect(opts.length, 4);
          expect(opts.where((o) => o.isCorrect).single.word, p.patient);
          expect(opts.map((o) => o.word).toSet().length, 4);
          for (final o in opts.where((o) => !o.isCorrect)) {
            expect(v.validPatients.contains(o.word), isFalse,
                reason: '${v.verb}: "${o.word}" is listed as valid but was offered as wrong');
          }
        }
      }
    }
  });

  test('example questions read naturally', () {
    final b = ExerciseBuilder(verbs, rng: Random(3));
    final cook = verbs.firstWhere((x) => x.verb == 'cook');
    expect(ExerciseBuilder.whoQuestion(cook), 'Who cooks?');
    expect(ExerciseBuilder.whatQuestion(cook, 'chef'), 'What does the chef cook?');
    // ignore: avoid_print
    print('Who cooks?  ${b.whoRound(cook, cook.pairs[0]).map((o) => o.word).join(' / ')}');
    // ignore: avoid_print
    print('What does the chef cook?  ${b.whatRound(cook, cook.pairs[0]).map((o) => o.word).join(' / ')}');
  });

  test('sentence rounds: 2 make sense, 2 do not', () {
    final b = ExerciseBuilder(verbs, rng: Random(1));
    for (final v in verbs) {
      final items = b.sentenceRound(v);
      expect(items.where((i) => i.makesSense).length, 2);
      expect(items.where((i) => !i.makesSense).length, 2);
    }
  });

  test('wrong-object pools (printed for clinician review)', () {
    final b = ExerciseBuilder(verbs);
    for (final v in verbs) {
      final pool = b.wrongObjectsFor(v)..sort();
      expect(pool.length, greaterThanOrEqualTo(10), reason: v.verb);
      // ignore: avoid_print
      print('${v.verb.padRight(6)} wrong objects: ${pool.join(', ')}');
    }
  });

  group('model scenarios (the model marks the answer, code checks taps)', () {
    // Real Llama-3.2-3B output for "drive" from the prompt test.
    Map<String, dynamic> drive() => {
          'verb_s': 'drives',
          'who': {'options': ['man', 'car', 'cloud', 'stone'], 'answer': 'man'},
          'what': {'options': ['car', 'song', 'anger', 'sky'], 'answer': 'car'},
          'where': {'options': ['on the road', 'under the sea', 'in the sky', 'on the moon'], 'answer': 'on the road'},
          'when': {'options': ['before dawn', 'while sleeping', 'while swimming', 'before he was born'], 'answer': 'before dawn'},
          'why': {'options': ['to go to work', 'to grow wings', 'to make it rain', 'to turn into a fish'], 'answer': 'to go to work'},
        };

    test('valid output becomes a scenario; only the marked answer counts as correct', () {
      final s = Scenario.fromModel('drive', drive(), rng: Random(1));
      expect(s.agent, 'man');
      expect(s.patient, 'car');
      expect(s.sentence, 'The man drives the car.');
      expect(s.prompt(QKind.what), 'What does the man drive?');
      expect(s.prompt(QKind.when), 'When does the man drive the car?');
      final when = s.questions[QKind.when]!;
      expect(when.options.length, 4);
      expect(when.isCorrect('before dawn'), isTrue);
      expect(when.isCorrect('while sleeping'), isFalse);
      // round-trips through storage
      final back = Scenario.fromJson(jsonDecode(jsonEncode(s.toJson())) as Map<String, dynamic>);
      expect(back.questions[QKind.why]!.answer, 'to go to work');
    });

    test('answers and options are normalised (case, full stops)', () {
      final j = drive();
      j['who'] = {'options': ['Man.', 'Car', 'Cloud', 'Stone'], 'answer': 'man'};
      expect(Scenario.fromModel('drive', j).agent, 'man');
    });

    test('5 options are trimmed to the answer + 3 others', () {
      final j = drive();
      j['who'] = {'options': ['artist', 'stone', 'cloud', 'car', 'truck'], 'answer': 'artist'};
      final q = Scenario.fromModel('drive', j).questions[QKind.who]!;
      expect(q.options.length, 4);
      expect(q.options, contains('artist'));
    });

    test('rejected: answer not among the options', () {
      final j = drive();
      j['what'] = {'options': ['bus', 'song', 'anger', 'sky'], 'answer': 'car'};
      expect(() => Scenario.fromModel('drive', j), throwsFormatException);
    });

    test('rejected: fewer than 4 different options', () {
      final j = drive();
      j['why'] = {'options': ['to go to work', 'to go to work', 'to fly'], 'answer': 'to go to work'};
      expect(() => Scenario.fromModel('drive', j), throwsFormatException);
    });

    test('verb forms are built by code, not trusted from the model', () {
      expect(Scenario.thirdPerson('wash'), 'washes'); // the model wrote "wash"
      expect(Scenario.thirdPerson('carry'), 'carries');
      expect(Scenario.thirdPerson('play'), 'plays');
      expect(Scenario.thirdPerson('fix'), 'fixes');
      expect(Scenario.thirdPerson('go'), 'goes');
      expect(Scenario.thirdPerson('cook'), 'cooks');
    });

    test('prompt asks for different people on repeat requests', () {
      final p = LlmService.userPrompt('cook', avoidPeople: ['chef']);
      expect(p, contains('Verb: "cook"'));
      expect(p, contains('(not chef)'));
    });
  });
}
