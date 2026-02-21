// Stub for dart:io File when running on web
class File {
  final String path;
  File(this.path);
  Future<List<int>> readAsBytes() async => [];
}
