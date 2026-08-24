import 'package:flutter/foundation.dart' show kIsWeb;
import 'package:path/path.dart' as p;
import 'package:sqflite/sqflite.dart';

class LocalHistoryService {
  LocalHistoryService._();
  static final LocalHistoryService instance = LocalHistoryService._();

  static const String _dbName = 'nate_history.db';
  static const int _version = 1;

  Database? _db;
  bool _disabled = kIsWeb;

  Future<Database> _getDatabase() async {
    if (_disabled) {
      throw UnsupportedError('SQLite not available');
    }
    if (_db != null && _db!.isOpen) return _db!;
    try {
      final path = p.join(await getDatabasesPath(), _dbName);
      _db = await openDatabase(
        path,
        version: _version,
        onCreate: _onCreate,
      );
      return _db!;
    } catch (e) {
      _disabled = true;
      print('[LocalHistoryService] SQLite disabled — using server history only: $e');
      rethrow;
    }
  }

  Future<void> _onCreate(Database db, int version) async {
    await db.execute('''
      CREATE TABLE history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id TEXT,
        user_text TEXT NOT NULL,
        ai_text TEXT NOT NULL,
        created_at TEXT NOT NULL
      )
    ''');
    await db.execute('''
      CREATE VIRTUAL TABLE history_fts USING fts5(
        user_text,
        ai_text,
        content='history',
        content_rowid='id'
      )
    ''');
    await db.execute('''
      CREATE TRIGGER history_ai AFTER INSERT ON history BEGIN
        INSERT INTO history_fts(rowid, user_text, ai_text)
        VALUES (new.id, new.user_text, new.ai_text);
      END
    ''');
    await db.execute('''
      CREATE TRIGGER history_ad AFTER DELETE ON history BEGIN
        INSERT INTO history_fts(history_fts, rowid, user_text, ai_text)
        VALUES ('delete', old.id, old.user_text, old.ai_text);
      END
    ''');
    await db.execute('''
      CREATE TRIGGER history_au AFTER UPDATE ON history BEGIN
        INSERT INTO history_fts(history_fts, rowid, user_text, ai_text)
        VALUES ('delete', old.id, old.user_text, old.ai_text);
        INSERT INTO history_fts(rowid, user_text, ai_text)
        VALUES (new.id, new.user_text, new.ai_text);
      END
    ''');
  }

  Future<void> insertEntry({
    String? sessionId,
    required String userText,
    required String aiText,
    required String createdAt,
  }) async {
    if (_disabled) return;
    try {
      final db = await _getDatabase();
      await db.insert(
        'history',
        {
          'session_id': sessionId,
          'user_text': userText,
          'ai_text': aiText,
          'created_at': createdAt,
        },
      );
    } catch (e) {
      // _disabled is set by _getDatabase on failure
    }
  }

  Future<List<Map<String, dynamic>>> search(String query, {int limit = 30}) async {
    if (_disabled) return [];
    try {
      final db = await _getDatabase();
      final rows = await db.rawQuery(
        '''
        SELECT h.* FROM history h
        INNER JOIN history_fts f ON h.id = f.rowid
        WHERE f MATCH ?
        ORDER BY h.created_at DESC
        LIMIT ?
        ''',
        [query, limit],
      );
      return rows;
    } catch (e) {
      print('[LocalHistoryService] search failed: $e');
      return [];
    }
  }

  Future<List<Map<String, dynamic>>> getRecentEntries({int limit = 50}) async {
    if (_disabled) return [];
    try {
      final db = await _getDatabase();
      return db.query(
        'history',
        orderBy: 'created_at DESC',
        limit: limit,
      );
    } catch (e) {
      print('[LocalHistoryService] getRecentEntries failed: $e');
      return [];
    }
  }

  Future<int> getEntryCount() async {
    if (_disabled) return 0;
    try {
      final db = await _getDatabase();
      final result = await db.rawQuery('SELECT COUNT(*) as c FROM history');
      return Sqflite.firstIntValue(result) ?? 0;
    } catch (e) {
      print('[LocalHistoryService] getEntryCount failed: $e');
      return 0;
    }
  }

  Future<List<Map<String, dynamic>>> exportAll() async {
    if (_disabled) return [];
    try {
      final db = await _getDatabase();
      return db.query('history', orderBy: 'created_at ASC');
    } catch (e) {
      print('[LocalHistoryService] exportAll failed: $e');
      return [];
    }
  }

  /// Returns entries created after [isoTimestamp] for delta sync to server.
  /// Drop local rows older than [isoTimestamp] (ISO-8601). Used when
  /// the server reports conversation_history tombstones so the device
  /// does not keep rows the retention policy already deleted.
  Future<int> deleteOlderThan(String isoTimestamp) async {
    if (_disabled) return 0;
    try {
      final db = await _getDatabase();
      return await db.delete(
        'history',
        where: 'created_at < ?',
        whereArgs: [isoTimestamp],
      );
    } catch (e) {
      print('[LocalHistoryService] deleteOlderThan failed: $e');
      return 0;
    }
  }

  Future<List<Map<String, dynamic>>> getEntriesAfter(String isoTimestamp, {int limit = 200}) async {
    if (_disabled) return [];
    try {
      final db = await _getDatabase();
      return db.query(
        'history',
        where: 'created_at > ?',
        whereArgs: [isoTimestamp],
        orderBy: 'created_at ASC',
        limit: limit,
      );
    } catch (e) {
      print('[LocalHistoryService] getEntriesAfter failed: $e');
      return [];
    }
  }

  Future<void> close() async {
    if (_disabled) return;
    if (_db != null && _db!.isOpen) {
      await _db!.close();
      _db = null;
    }
  }
}
