import 'dart:convert';
import 'dart:io';
import 'dart:math';

import 'package:flutter/services.dart';
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

  group('one question per request (who, what, where, when, why)', () {
    Question q(String answer, List<String> wrong) => Question([answer, ...wrong], answer);
    final done = {
      QKind.who: q('a chef', ['cloud', 'candle', 'cup']),
      QKind.what: q('the egg', ['boredom', 'tomorrow', 'a song']),
      QKind.where: q('in the kitchen', ['on the sun', 'inside a volcano', 'in outer space']),
      QKind.when: q('in the morning', ['while asleep', 'before he was born', 'in the year 3000']),
    };

    test('each part prompt carries the sentence so far, built by code, and says what answer and wrong options are', () {
      expect(LlmService.partPrompt('cook', QKind.who, {}),
          'VNeST "cook". who? Answer: a person (1 or 2 words) who often cooks things. Wrong: 3 things that cannot cook.');
      expect(LlmService.partPrompt('cook', QKind.who, {}, avoidPeople: ['chef', 'grandma']),
          endsWith('The answer must not be: chef, grandma.'));
      expect(LlmService.partPrompt('cook', QKind.what, done),
          'VNeST "cook". what? The chef cooks ___. Answer: what the chef cooks. Wrong: 3 things nobody can cook.');
      expect(LlmService.partPrompt('cook', QKind.where, done), startsWith('VNeST "cook". where? The chef cooks the egg ___. '));
      expect(LlmService.partPrompt('cook', QKind.when, done),
          startsWith('VNeST "cook". when? The chef cooks the egg in the kitchen ___. '));
      expect(LlmService.partPrompt('cook', QKind.why, done),
          startsWith('VNeST "cook". why? The chef cooks the egg in the kitchen in the morning ___. '));
      // No prompt contains a phrase the model could copy as a ready-made option ("A person who often cooks something").
      expect(LlmService.partPrompt('cook', QKind.who, {}), isNot(contains('something')));
    });

    test('one part is checked on its own (fixed-field reply: answer + wrong1..3)', () {
      final ok = Scenario.partFromModel(QKind.where,
          {'answer': 'In the kitchen', 'wrong1': 'On the sun.', 'wrong2': 'inside a volcano', 'wrong3': 'in space'});
      expect(ok.answer, 'in the kitchen');
      expect(ok.options.length, 4);
      expect(ok.options, contains('in the kitchen'));
      expect(() => Scenario.partFromModel(QKind.who, {'answer': 'chef', 'wrong1': 'cloud', 'wrong2': 'cloud', 'wrong3': 'chef'}),
          throwsA(isA<FormatException>())); // only 2 different options
      expect(() => Scenario.partFromModel(QKind.who, {'answer': '', 'wrong1': 'a', 'wrong2': 'b', 'wrong3': 'c'}),
          throwsA(isA<FormatException>())); // empty answer
      // the older {"options", "answer"} shape still works
      expect(() => Scenario.partFromModel(QKind.who, {'options': ['chef', 'cloud', 'cup'], 'answer': 'chef'}),
          throwsA(isA<FormatException>()));
      expect(() => Scenario.partFromModel(QKind.what, {'options': ['egg', 'a', 'b', 'c'], 'answer': 'soup'}),
          throwsA(isA<FormatException>()));
    });

    test('who and what must differ, also with articles ("a chef" vs "chef")', () {
      expect(() => Scenario.checkWhoWhat(q('a chef', ['x', 'y', 'z']), q('chef', ['x', 'y', 'z'])), throwsA(isA<FormatException>()));
      expect(Scenario.noun('the egg'), 'egg');
      final s = Scenario(verb: 'cook', questions: Map.of(done), source: ScenarioSource.llm);
      expect(s.sentence, 'The chef cooks the egg.');
      expect(s.isComplete, isFalse);
    });
  });

  group('part-by-part writing against a fake engine', () {
    TestWidgetsFlutterBinding.ensureInitialized();
    const channel = MethodChannel('vnest/llm');
    final messenger = TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger;

    /// Replies to "generateJson" in order; records the prompts it was sent.
    List<String> fake(List<String> replies) {
      final prompts = <String>[];
      var i = 0;
      messenger.setMockMethodCallHandler(channel, (call) async {
        switch (call.method) {
          case 'status':
            return {'modelDir': '/x', 'modelPresent': true, 'loaded': true};
          case 'generateJson':
            prompts.add((call.arguments as Map)['user'] as String);
            return {'text': replies[i++], 'ms': 1000, 'completionTokens': 30, 'decodeTps': 7.0};
        }
        return null;
      });
      return prompts;
    }

    String part(String answer, List<String> wrong) =>
        jsonEncode({'answer': answer, 'wrong1': wrong[0], 'wrong2': wrong[1], 'wrong3': wrong[2]});
    final good = [
      part('chef', ['cloud', 'candle', 'cup']),
      part('egg', ['boredom', 'tomorrow', 'a song']),
      part('in the kitchen', ['on the sun', 'inside a volcano', 'in outer space']),
      part('in the morning', ['while asleep', 'before he was born', 'in the year 3000']),
      part('to make breakfast', ['to grow wings', 'to become a tree', 'to stop the sun']),
    ];

    Future<LlmService> ready() async {
      final llm = LlmService();
      await llm.refresh(); // fake engine says: loaded
      return llm;
    }

    tearDown(() => messenger.setMockMethodCallHandler(channel, null));

    test('five requests, in order, each given the earlier parts; every part reported as it passes', () async {
      final prompts = fake(good);
      final llm = await ready();
      final reported = <QKind>[];
      final r = await llm.generateScenario('cook', onPart: (k, _) => reported.add(k));
      expect(r.scenario, isNotNull, reason: r.rejectedReason);
      expect(reported, QKind.values);
      expect(prompts.length, 5);
      expect(prompts[2], startsWith('VNeST "cook". where? The chef cooks the egg ___. '));
      expect(r.scenario!.sentence, 'The chef cooks the egg.');
      expect(r.ms, 5000);
      expect(r.tokens, 150);
    });

    test('a bad part is redone on its own; earlier parts are kept', () async {
      final prompts = fake([good[0], good[1], 'not json', part('x', ['x', 'x', 'x']), good[2], good[3], good[4]]);
      final llm = await ready();
      final r = await llm.generateScenario('cook');
      expect(r.scenario, isNotNull, reason: r.rejectedReason);
      expect(prompts.length, 7);
      expect(prompts.where((p) => p.contains('where?')).length, 3); // 2 failed tries + 1 good
      expect(prompts.where((p) => p.contains('who?')).length, 1); // who not redone
    });

    test('gives up after 3 tries of one part', () async {
      fake([good[0], 'bad', 'bad', 'bad']);
      final llm = await ready();
      final r = await llm.generateScenario('cook');
      expect(r.scenario, isNull);
      expect(r.rejectedReason, contains('after 3 tries'));
    });

    test('who must be a new person; what must differ from who', () async {
      final prompts = fake([part('chef', ['a', 'b', 'c']), good[0].replaceAll('chef', 'baker'),
        part('baker', ['x', 'y', 'z']), good[1], good[2], good[3], good[4]]);
      final llm = await ready();
      final r = await llm.generateScenario('cook', avoidPeople: ['chef']);
      expect(r.scenario, isNotNull, reason: r.rejectedReason);
      expect(r.scenario!.agent, 'baker');
      expect(r.scenario!.patient, 'egg');
      expect(prompts.first, endsWith('The answer must not be: chef.'));
    });

    test('stops between parts when asked (e.g. the patient opened another verb)', () async {
      fake(good);
      final llm = await ready();
      var calls = 0;
      final r = await llm.generateScenario('cook', keepGoing: () => ++calls <= 2);
      expect(r.rejectedReason, 'stopped');
    });
  });
}
