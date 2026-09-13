import 'package:flutter_test/flutter_test.dart';

import 'package:runsense/main.dart';

void main() {
  testWidgets('Home screen shows RunSense title', (WidgetTester tester) async {
    await tester.pumpWidget(const RunSenseApp());
    await tester.pump(const Duration(milliseconds: 350)); // mocked getWeekPlan() delay

    expect(find.text('RunSense'), findsOneWidget);
  });
}
