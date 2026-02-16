/// ZEFCP Offline Buffer — SQLite-based Fragment & Emission Storage
/// Stores ZEFCP fragments and trail emissions when offline for later sync
/// Layer 2 Data Persistence: Offline-first fragment buffering

import 'dart:async';
import 'dart:convert';
import 'package:sqflite/sqflite.dart';
import 'package:path/path.dart';
import 'package:path_provider/path_provider.dart';

/// Buffer entry type
enum BufferEntryType {
  /// ZEFCP fragment
  fragment,
  
  /// Trail emission (observation data)
  emission,
}

/// Buffer entry model
class BufferEntry {
  /// Database ID
  final int? id;
  
  /// Entry type (fragment or emission)
  final BufferEntryType type;
  
  /// JSON payload
  final Map<String, dynamic> payloadJson;
  
  /// Creation timestamp
  final DateTime createdAt;
  
  /// Whether entry has been synced to backend
  final bool synced;
  
  BufferEntry({
    this.id,
    required this.type,
    required this.payloadJson,
    required this.createdAt,
    this.synced = false,
  });
  
  /// Convert to map for database storage
  Map<String, dynamic> toMap() {
    return {
      'id': id,
      'type': type.name,
      'payload_json': jsonEncode(payloadJson),
      'created_at': createdAt.toIso8601String(),
      'synced': synced ? 1 : 0,
    };
  }
  
  /// Create from database map
  factory BufferEntry.fromMap(Map<String, dynamic> map) {
    return BufferEntry(
      id: map['id'] as int?,
      type: BufferEntryType.values.firstWhere(
        (e) => e.name == map['type'] as String,
        orElse: () => BufferEntryType.fragment,
      ),
      payloadJson: jsonDecode(map['payload_json'] as String) as Map<String, dynamic>,
      createdAt: DateTime.parse(map['created_at'] as String),
      synced: (map['synced'] as int) == 1,
    );
  }
}

/// SQLite-based offline buffer for ZEFCP fragments and emissions
/// 
/// Provides persistent storage for fragments and trail emissions when
/// the device is offline or cannot immediately sync to the backend.
/// 
/// Features:
/// - Auto-creates database and tables on first use
/// - Configurable max buffer size (default: 10000 entries)
/// - Automatic purging of old synced entries (24+ hours)
/// - Thread-safe operations
/// - Efficient batch operations
class OfflineBuffer {
  static const String _dbName = 'zefcp_offline_buffer.db';
  static const String _tableName = 'buffer_entries';
  static const int _dbVersion = 1;
  
  /// Default maximum buffer size
  static const int defaultMaxBufferSize = 10000;
  
  /// Default purge age (24 hours)
  static const Duration defaultPurgeAge = Duration(hours: 24);
  
  Database? _database;
  final int _maxBufferSize;
  
  /// Initialize offline buffer
  /// 
  /// [maxBufferSize] Maximum number of entries before purging (default: 10000)
  OfflineBuffer({int maxBufferSize = defaultMaxBufferSize})
      : _maxBufferSize = maxBufferSize;
  
  /// Get database instance (creates if needed)
  Future<Database> _getDatabase() async {
    if (_database != null) return _database!;
    
    final documentsDirectory = await getApplicationDocumentsDirectory();
    final path = join(documentsDirectory.path, _dbName);
    
    _database = await openDatabase(
      path,
      version: _dbVersion,
      onCreate: (db, version) async {
        await db.execute('''
          CREATE TABLE $_tableName (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            type TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            synced INTEGER NOT NULL DEFAULT 0
          )
        ''');
        
        // Index for efficient synced queries
        await db.execute('''
          CREATE INDEX idx_synced ON $_tableName(synced)
        ''');
        
        // Index for efficient type queries
        await db.execute('''
          CREATE INDEX idx_type ON $_tableName(type)
        ''');
        
        // Index for efficient date-based purging
        await db.execute('''
          CREATE INDEX idx_created_at ON $_tableName(created_at)
        ''');
        
        print('[ZEFCP OfflineBuffer] Database created at $path');
      },
    );
    
    return _database!;
  }
  
  /// Buffer a ZEFCP fragment for later sync
  /// 
  /// [fragmentData] Fragment data as map (will be JSON encoded)
  /// 
  /// Returns true if buffered, false if buffer is full
  Future<bool> bufferFragment(Map<String, dynamic> fragmentData) async {
    try {
      final db = await _getDatabase();
      
      // Check buffer size
      final count = await getCount();
      if (count >= _maxBufferSize) {
        // Try to purge old synced entries first
        await purgeOld();
        final newCount = await getCount();
        if (newCount >= _maxBufferSize) {
          print('[ZEFCP OfflineBuffer] Buffer full, cannot buffer fragment');
          return false;
        }
      }
      
      final entry = BufferEntry(
        type: BufferEntryType.fragment,
        payloadJson: fragmentData,
        createdAt: DateTime.now(),
        synced: false,
      );
      
      await db.insert(_tableName, entry.toMap());
      
      print('[ZEFCP OfflineBuffer] Buffered fragment (total: ${count + 1})');
      return true;
    } catch (e) {
      print('[ZEFCP OfflineBuffer] Error buffering fragment: $e');
      return false;
    }
  }
  
  /// Buffer a trail emission for later sync
  /// 
  /// [emissionData] Emission data as map (will be JSON encoded)
  /// 
  /// Returns true if buffered, false if buffer is full
  Future<bool> bufferEmission(Map<String, dynamic> emissionData) async {
    try {
      final db = await _getDatabase();
      
      // Check buffer size
      final count = await getCount();
      if (count >= _maxBufferSize) {
        // Try to purge old synced entries first
        await purgeOld();
        final newCount = await getCount();
        if (newCount >= _maxBufferSize) {
          print('[ZEFCP OfflineBuffer] Buffer full, cannot buffer emission');
          return false;
        }
      }
      
      final entry = BufferEntry(
        type: BufferEntryType.emission,
        payloadJson: emissionData,
        createdAt: DateTime.now(),
        synced: false,
      );
      
      await db.insert(_tableName, entry.toMap());
      
      print('[ZEFCP OfflineBuffer] Buffered emission (total: ${count + 1})');
      return true;
    } catch (e) {
      print('[ZEFCP OfflineBuffer] Error buffering emission: $e');
      return false;
    }
  }
  
  /// Get all unsynced entries
  /// 
  /// [limit] Maximum number of entries to return (default: no limit)
  /// 
  /// Returns list of unsynced buffer entries
  Future<List<BufferEntry>> getUnsynced({int? limit}) async {
    try {
      final db = await _getDatabase();
      
      final maps = await db.query(
        _tableName,
        where: 'synced = ?',
        whereArgs: [0],
        orderBy: 'created_at ASC',
        limit: limit,
      );
      
      return maps.map((map) => BufferEntry.fromMap(map)).toList();
    } catch (e) {
      print('[ZEFCP OfflineBuffer] Error getting unsynced entries: $e');
      return [];
    }
  }
  
  /// Mark entries as synced
  /// 
  /// [ids] List of entry IDs to mark as synced
  Future<void> markSynced(List<int> ids) async {
    if (ids.isEmpty) return;
    
    try {
      final db = await _getDatabase();
      
      final placeholders = ids.map((_) => '?').join(',');
      await db.update(
        _tableName,
        {'synced': 1},
        where: 'id IN ($placeholders)',
        whereArgs: ids,
      );
      
      print('[ZEFCP OfflineBuffer] Marked ${ids.length} entries as synced');
    } catch (e) {
      print('[ZEFCP OfflineBuffer] Error marking entries as synced: $e');
    }
  }
  
  /// Purge old synced entries
  /// 
  /// [purgeAge] Age threshold for purging (default: 24 hours)
  /// 
  /// Returns number of entries purged
  Future<int> purgeOld({Duration? purgeAge}) async {
    final age = purgeAge ?? defaultPurgeAge;
    final cutoff = DateTime.now().subtract(age);
    
    try {
      final db = await _getDatabase();
      
      final count = await db.delete(
        _tableName,
        where: 'synced = ? AND created_at < ?',
        whereArgs: [1, cutoff.toIso8601String()],
      );
      
      if (count > 0) {
        print('[ZEFCP OfflineBuffer] Purged $count old synced entries');
      }
      
      return count;
    } catch (e) {
      print('[ZEFCP OfflineBuffer] Error purging old entries: $e');
      return 0;
    }
  }
  
  /// Get total count of buffer entries
  Future<int> getCount() async {
    try {
      final db = await _getDatabase();
      final result = await db.rawQuery('SELECT COUNT(*) as count FROM $_tableName');
      return Sqflite.firstIntValue(result) ?? 0;
    } catch (e) {
      print('[ZEFCP OfflineBuffer] Error getting count: $e');
      return 0;
    }
  }
  
  /// Get count of unsynced entries
  Future<int> getUnsyncedCount() async {
    try {
      final db = await _getDatabase();
      final result = await db.rawQuery(
        'SELECT COUNT(*) as count FROM $_tableName WHERE synced = ?',
        [0],
      );
      return Sqflite.firstIntValue(result) ?? 0;
    } catch (e) {
      print('[ZEFCP OfflineBuffer] Error getting unsynced count: $e');
      return 0;
    }
  }
  
  /// Clear all buffer entries (use with caution)
  Future<void> clearAll() async {
    try {
      final db = await _getDatabase();
      await db.delete(_tableName);
      print('[ZEFCP OfflineBuffer] Cleared all buffer entries');
    } catch (e) {
      print('[ZEFCP OfflineBuffer] Error clearing buffer: $e');
    }
  }
  
  /// Close database connection
  Future<void> close() async {
    await _database?.close();
    _database = null;
    print('[ZEFCP OfflineBuffer] Database closed');
  }
  
  /// Dispose resources
  void dispose() {
    close();
  }
}
