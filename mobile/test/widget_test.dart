// This is a basic Flutter widget test.
//
// To perform an interaction with a widget in your test, use the WidgetTester
// utility in the flutter_test package. For example, you can send tap and scroll
// gestures. You can also use WidgetTester to find child widgets in the widget
// tree, read text, and verify that the values of widget properties are correct.

import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:little_nate/main.dart' show SovereignCovenantDoc;
import 'package:little_nate/metrics_widgets.dart';
import 'package:little_nate/screens/ai_consent_screen.dart';
import 'package:little_nate/screens/nevedal_reports_screen.dart';

void main() {
  testWidgets('AI consent displays medical safety disclaimer',
      (WidgetTester tester) async {
    await tester.pumpWidget(MaterialApp(
      home: AiConsentScreen(
        profile: const {},
        username: 'audit_client',
        password: 'unused',
        buildNextScreen: () => const SizedBox.shrink(),
      ),
    ));

    expect(find.text('How Little Nate Works'), findsOneWidget);
    expect(find.textContaining('Seek a doctor'), findsOneWidget);
  });

  testWidgets('iOS covenant excludes biometric claims',
      (WidgetTester tester) async {
    debugDefaultTargetPlatformOverride = TargetPlatform.iOS;
    try {
      await tester.pumpWidget(MaterialApp(
        home: Scaffold(
          body: SovereignCovenantDoc(
            consentGiven: false,
            onChanged: (_) {},
            color: Colors.amber,
          ),
        ),
      ));

      expect(find.textContaining("Seek a doctor's advice"), findsOneWidget);
      expect(find.textContaining('AI DATA PROCESSING'), findsOneWidget);
      expect(find.textContaining('Voiceprint'), findsNothing);
      expect(find.textContaining('Facial Geometry'), findsNothing);
    } finally {
      debugDefaultTargetPlatformOverride = null;
    }
  });

  testWidgets('iOS hides clinical metric widgets',
      (WidgetTester tester) async {
    debugDefaultTargetPlatformOverride = TargetPlatform.iOS;
    try {
      await tester.pumpWidget(const MaterialApp(
        home: Scaffold(
          body: Column(
            children: [
              NevedalMetricsGrid(metrics: {'C_emo': 0.9}),
              RiskBadge(riskLevel: 'HIGH'),
              MoodIndicator(mood: 'distressed'),
            ],
          ),
        ),
      ));

      expect(find.text('NEVEDAL METRICS'), findsNothing);
      expect(find.textContaining('HIGH RISK'), findsNothing);
      expect(find.text('Distressed'), findsNothing);
    } finally {
      debugDefaultTargetPlatformOverride = null;
    }
  });

  testWidgets('iOS report route cannot load clinical data',
      (WidgetTester tester) async {
    debugDefaultTargetPlatformOverride = TargetPlatform.iOS;
    try {
      await tester.pumpWidget(const MaterialApp(
        home: NevedalReportsScreen(profile: {}),
      ));

      expect(find.text('This feature is not available on iOS.'), findsOneWidget);
      expect(find.text('Coherence Dashboard'), findsNothing);
      expect(find.byType(CircularProgressIndicator), findsNothing);
    } finally {
      debugDefaultTargetPlatformOverride = null;
    }
  });
}
