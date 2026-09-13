class Athlete {
  final String id;
  final String name;
  final List<String> guideDays; // e.g. ["Tue", "Sat"]
  final String preferredVenue; // "track" | "treadmill" | "outdoor"

  const Athlete({
    required this.id,
    required this.name,
    required this.guideDays,
    required this.preferredVenue,
  });
}
