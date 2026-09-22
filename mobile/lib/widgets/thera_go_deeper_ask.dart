/// Shared Go Deeper ask so vault + Thera-World hot button stay unique per panel.
String theraGoDeeperAsk({
  required String panelId,
  String imageUrl = '',
  String narrative = '',
  String character = '',
  String biome = '',
}) {
  final imgTag = imageUrl.trim().isNotEmpty ? '[SSE Image:${imageUrl.trim()}]' : '';
  final hook = theraGoDeeperSceneHook(
    narrative: narrative,
    character: character,
    biome: biome,
  );
  if (panelId.trim().isEmpty || panelId == 'archetype') {
    final fmtBiome = biome.replaceAll('_', ' ').trim();
    return '$imgTag[Story Panel: journey] Biome: $fmtBiome. $hook';
  }
  return '$imgTag[SSE Panel:$panelId] I want to go deeper with you on this panel. $hook';
}

String theraGoDeeperSceneHook({
  String narrative = '',
  String character = '',
  String biome = '',
}) {
  final scene = _sceneClip(narrative);
  final who = character.trim();
  final land = biome.replaceAll('_', ' ').trim();
  final skip =
      'Walk Sense, Image, Feel, Think with me on what is actually in this scene. '
      'Do not use the stock three journaling prompts.';
  if (scene.isNotEmpty) {
    final prefix = who.isNotEmpty ? '$who. ' : '';
    return '${prefix}Scene: $scene $skip';
  }
  if (who.isNotEmpty || land.isNotEmpty) {
    final bits = <String>[
      if (who.isNotEmpty) who,
      if (land.isNotEmpty) 'in $land',
    ];
    return '${bits.join(' ')}. $skip';
  }
  return skip;
}

String _sceneClip(String narrative, {int max = 160}) {
  final t = narrative.replaceAll(RegExp(r'\s+'), ' ').trim();
  if (t.isEmpty) return '';
  if (t.length <= max) return t;
  return '${t.substring(0, max).trim()}…';
}
