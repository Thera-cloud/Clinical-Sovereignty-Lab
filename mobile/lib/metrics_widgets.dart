// =============================================================================
// LITTLE NATE - METRICS VIEW COMPONENTS
// Version: 1.0 | January 23, 2026
// 
// Reusable widgets for displaying Nevedal metrics, mood history, and risk levels.
// Import into main.dart and use across Client, Coach, and Admin screens.
// =============================================================================

import 'package:flutter/material.dart';
import 'dart:math' as math;

// =============================================================================
// COLOR PALETTE (Sovereign Theme)
// =============================================================================
class SovereignColors {
  static const Color background = Color(0xFF0A0A0F);
  static const Color surface = Color(0xFF1A1A2E);
  static const Color card = Color(0xFF16213E);
  static const Color gold = Color(0xFFFFD700);
  static const Color cyan = Color(0xFF00FFFF);
  static const Color purple = Color(0xFF9D4EDD);
  static const Color pink = Color(0xFFFF006E);
  static const Color green = Color(0xFF00F5D4);
  static const Color red = Color(0xFFFF4757);
  static const Color orange = Color(0xFFFF9F1C);
  static const Color blue = Color(0xFF4361EE);
  
  // Risk level colors
  static const Color riskLow = Color(0xFF00F5D4);
  static const Color riskMedium = Color(0xFFFFD700);
  static const Color riskHigh = Color(0xFFFF9F1C);
  static const Color riskCritical = Color(0xFFFF4757);
  
  // Mood colors
  static const Color moodHappy = Color(0xFF00F5D4);
  static const Color moodNeutral = Color(0xFF4361EE);
  static const Color moodSad = Color(0xFF9D4EDD);
  static const Color moodAnxious = Color(0xFFFF9F1C);
  static const Color moodAngry = Color(0xFFFF4757);
}

// =============================================================================
// 1. NEVEDAL GAUGE WIDGET - Circular progress indicator for metrics
// =============================================================================
class NevedalGauge extends StatelessWidget {
  final String label;
  final double value; // 0.0 to 1.0
  final Color color;
  final String? subtitle;
  final double size;
  final bool showPercentage;

  const NevedalGauge({
    super.key,
    required this.label,
    required this.value,
    this.color = SovereignColors.cyan,
    this.subtitle,
    this.size = 100,
    this.showPercentage = true,
  });

  @override
  Widget build(BuildContext context) {
    return Column(
      mainAxisSize: MainAxisSize.min,
      children: [
        SizedBox(
          width: size,
          height: size,
          child: Stack(
            alignment: Alignment.center,
            children: [
              // Background ring
              SizedBox(
                width: size,
                height: size,
                child: CircularProgressIndicator(
                  value: 1.0,
                  strokeWidth: 8,
                  backgroundColor: Colors.transparent,
                  valueColor: AlwaysStoppedAnimation(color.withOpacity(0.15)),
                ),
              ),
              // Value ring
              SizedBox(
                width: size,
                height: size,
                child: CircularProgressIndicator(
                  value: value.clamp(0.0, 1.0),
                  strokeWidth: 8,
                  backgroundColor: Colors.transparent,
                  valueColor: AlwaysStoppedAnimation(color),
                  strokeCap: StrokeCap.round,
                ),
              ),
              // Center text
              Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  if (showPercentage)
                    Text(
                      "${(value * 100).toInt()}%",
                      style: TextStyle(
                        color: color,
                        fontSize: size * 0.22,
                        fontWeight: FontWeight.bold,
                        fontFamily: 'Courier',
                      ),
                    ),
                  if (subtitle != null)
                    Text(
                      subtitle!,
                      style: TextStyle(
                        color: Colors.grey,
                        fontSize: size * 0.1,
                      ),
                    ),
                ],
              ),
            ],
          ),
        ),
        const SizedBox(height: 8),
        Text(
          label,
          style: TextStyle(
            color: Colors.white70,
            fontSize: size * 0.12,
            fontWeight: FontWeight.w500,
          ),
          textAlign: TextAlign.center,
        ),
      ],
    );
  }
}

// =============================================================================
// 2. NEVEDAL METRICS GRID - Full metrics dashboard
// =============================================================================
class NevedalMetricsGrid extends StatelessWidget {
  final Map<String, dynamic> metrics;
  final bool compact;

  const NevedalMetricsGrid({
    super.key,
    required this.metrics,
    this.compact = false,
  });

  @override
  Widget build(BuildContext context) {
    final double gaugeSize = compact ? 70.0 : 90.0;
    
    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: SovereignColors.surface.withOpacity(0.5),
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: Colors.white10),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              const Icon(Icons.analytics, color: SovereignColors.cyan, size: 20),
              const SizedBox(width: 8),
              const Text(
                "NEVEDAL METRICS",
                style: TextStyle(
                  color: SovereignColors.cyan,
                  fontWeight: FontWeight.bold,
                  letterSpacing: 1.5,
                  fontSize: 12,
                ),
              ),
              const Spacer(),
              _buildRiskBadge(metrics['risk_level'] ?? 'LOW'),
            ],
          ),
          const SizedBox(height: 16),
          
          // Primary metrics row
          Row(
            mainAxisAlignment: MainAxisAlignment.spaceEvenly,
            children: [
              NevedalGauge(
                // Chat-path vault score is lexicon word-list sentiment (v1),
                // NOT Nevedal Formula C_emo — do not label as C_emo.
                label: "Text Sent.",
                value: _parseDouble(metrics['text_sentiment_v1'] ?? metrics['C_emo'] ?? metrics['coherence'] ?? metrics['coherence_score'] ?? 0.5),
                color: SovereignColors.cyan,
                size: gaugeSize,
              ),
              NevedalGauge(
                label: "GAP",
                value: _parseDouble(metrics['GAP'] ?? metrics['growth'] ?? metrics['growth_potential'] ?? 0.3),
                color: SovereignColors.purple,
                size: gaugeSize,
              ),
              NevedalGauge(
                label: "Quantum",
                value: _parseDouble(metrics['Quantum'] ?? metrics['wellness'] ?? metrics['wellness_score'] ?? 0.5),
                color: SovereignColors.gold,
                size: gaugeSize,
              ),
            ],
          ),
          const SizedBox(height: 8),
          Text(
            'Text Sent. (v1) = lexicon word-list score from chat — not Nevedal Formula C_emo',
            textAlign: TextAlign.center,
            style: TextStyle(color: Colors.white38, fontSize: 10, fontStyle: FontStyle.italic),
          ),
          
          if (!compact) ...[
            const SizedBox(height: 20),
            const Divider(color: Colors.white10),
            const SizedBox(height: 12),
            
            // Secondary metrics
            Row(
              mainAxisAlignment: MainAxisAlignment.spaceEvenly,
              children: [
                _buildMiniMetric("Anxiety", metrics['anxiety_level'] ?? metrics['anxiety'] ?? 0, SovereignColors.orange),
                _buildMiniMetric("Stress", metrics['stress_level'] ?? metrics['stress'] ?? 0, SovereignColors.red),
                _buildMiniMetric("Engage", metrics['engagement'] ?? metrics['engage'] ?? 0.5, SovereignColors.green),
              ],
            ),
          ],
        ],
      ),
    );
  }

  Widget _buildMiniMetric(String label, dynamic value, Color color) {
    final double v = _parseDouble(value);
    return Column(
      children: [
        Text(
          "${(v * 100).toInt()}%",
          style: TextStyle(
            color: color,
            fontWeight: FontWeight.bold,
            fontSize: 18,
            fontFamily: 'Courier',
          ),
        ),
        Text(
          label,
          style: const TextStyle(color: Colors.grey, fontSize: 11),
        ),
      ],
    );
  }

  Widget _buildRiskBadge(String risk) {
    Color color;
    switch (risk.toUpperCase()) {
      case 'LOW':
        color = SovereignColors.riskLow;
        break;
      case 'MEDIUM':
        color = SovereignColors.riskMedium;
        break;
      case 'HIGH':
        color = SovereignColors.riskHigh;
        break;
      case 'CRITICAL':
        color = SovereignColors.riskCritical;
        break;
      default:
        color = SovereignColors.riskLow;
    }
    
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
      decoration: BoxDecoration(
        color: color.withOpacity(0.2),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: color),
      ),
      child: Text(
        risk.toUpperCase(),
        style: TextStyle(
          color: color,
          fontWeight: FontWeight.bold,
          fontSize: 10,
          letterSpacing: 1,
        ),
      ),
    );
  }

  double _parseDouble(dynamic value) {
    if (value == null) return 0.0;
    if (value is double) return value;
    if (value is int) return value.toDouble();
    if (value is String) {
      // Handle percentage strings like "50%"
      final cleaned = value.replaceAll('%', '');
      final parsed = double.tryParse(cleaned) ?? 0.0;
      return parsed > 1 ? parsed / 100 : parsed;
    }
    return 0.0;
  }
}

// =============================================================================
// 3. MOOD HISTORY CHART - Line chart showing mood over time
// =============================================================================
class MoodHistoryChart extends StatelessWidget {
  final List<dynamic> moodHistory;
  final double height;

  const MoodHistoryChart({
    super.key,
    required this.moodHistory,
    this.height = 150,
  });

  @override
  Widget build(BuildContext context) {
    if (moodHistory.isEmpty) {
      return Container(
        height: height,
        padding: const EdgeInsets.all(16),
        decoration: BoxDecoration(
          color: SovereignColors.surface.withOpacity(0.5),
          borderRadius: BorderRadius.circular(16),
          border: Border.all(color: Colors.white10),
        ),
        child: const Center(
          child: Text(
            "No mood data yet",
            style: TextStyle(color: Colors.grey),
          ),
        ),
      );
    }

    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: SovereignColors.surface.withOpacity(0.5),
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: Colors.white10),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: const [
              Icon(Icons.timeline, color: SovereignColors.purple, size: 20),
              SizedBox(width: 8),
              Text(
                "MOOD HISTORY",
                style: TextStyle(
                  color: SovereignColors.purple,
                  fontWeight: FontWeight.bold,
                  letterSpacing: 1.5,
                  fontSize: 12,
                ),
              ),
            ],
          ),
          const SizedBox(height: 16),
          SizedBox(
            height: height - 60,
            child: CustomPaint(
              size: Size.infinite,
              painter: MoodChartPainter(moodHistory: moodHistory),
            ),
          ),
          const SizedBox(height: 8),
          // Legend
          Row(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              _buildLegendItem("Engagement", SovereignColors.cyan),
              const SizedBox(width: 16),
              _buildLegendItem("Anxiety", SovereignColors.orange),
            ],
          ),
        ],
      ),
    );
  }

  Widget _buildLegendItem(String label, Color color) {
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        Container(
          width: 12,
          height: 3,
          decoration: BoxDecoration(
            color: color,
            borderRadius: BorderRadius.circular(2),
          ),
        ),
        const SizedBox(width: 4),
        Text(label, style: TextStyle(color: Colors.grey[400], fontSize: 10)),
      ],
    );
  }
}

class MoodChartPainter extends CustomPainter {
  final List<dynamic> moodHistory;

  MoodChartPainter({required this.moodHistory});

  @override
  void paint(Canvas canvas, Size size) {
    if (moodHistory.isEmpty) return;

    final engagementPaint = Paint()
      ..color = SovereignColors.cyan
      ..strokeWidth = 2
      ..style = PaintingStyle.stroke
      ..strokeCap = StrokeCap.round;

    final anxietyPaint = Paint()
      ..color = SovereignColors.orange
      ..strokeWidth = 2
      ..style = PaintingStyle.stroke
      ..strokeCap = StrokeCap.round;

    final gridPaint = Paint()
      ..color = Colors.white.withOpacity(0.05)
      ..strokeWidth = 1;

    // Draw grid
    for (int i = 0; i <= 4; i++) {
      final y = size.height * i / 4;
      canvas.drawLine(Offset(0, y), Offset(size.width, y), gridPaint);
    }

    // Prepare data points
    final int count = moodHistory.length;
    final double stepX = size.width / (count - 1).clamp(1, count);

    final engagementPath = Path();
    final anxietyPath = Path();

    for (int i = 0; i < count; i++) {
      final data = moodHistory[i];
      final x = i * stepX;
      
      // Engagement (inverted Y because canvas Y is top-down)
      final engagement = _parseDouble(data['engagement'] ?? 0.5);
      final engY = size.height * (1 - engagement.clamp(0.0, 1.0));
      
      // Anxiety
      final anxiety = _parseDouble(data['anxiety'] ?? 0);
      final anxY = size.height * (1 - anxiety.clamp(0.0, 1.0));

      if (i == 0) {
        engagementPath.moveTo(x, engY);
        anxietyPath.moveTo(x, anxY);
      } else {
        engagementPath.lineTo(x, engY);
        anxietyPath.lineTo(x, anxY);
      }

      // Draw dots
      canvas.drawCircle(Offset(x, engY), 3, Paint()..color = SovereignColors.cyan);
      if (anxiety > 0) {
        canvas.drawCircle(Offset(x, anxY), 3, Paint()..color = SovereignColors.orange);
      }
    }

    canvas.drawPath(engagementPath, engagementPaint);
    canvas.drawPath(anxietyPath, anxietyPaint);
  }

  double _parseDouble(dynamic value) {
    if (value == null) return 0.0;
    if (value is double) return value;
    if (value is int) return value.toDouble();
    if (value is String) return double.tryParse(value) ?? 0.0;
    return 0.0;
  }

  @override
  bool shouldRepaint(covariant CustomPainter oldDelegate) => true;
}

// =============================================================================
// 4. MOOD INDICATOR - Current mood display
// =============================================================================
class MoodIndicator extends StatelessWidget {
  final String mood;
  final String? trend;
  final bool large;

  const MoodIndicator({
    super.key,
    required this.mood,
    this.trend,
    this.large = false,
  });

  @override
  Widget build(BuildContext context) {
    final moodData = _getMoodData(mood);
    
    return Container(
      padding: EdgeInsets.all(large ? 20 : 12),
      decoration: BoxDecoration(
        color: moodData['color'].withOpacity(0.1),
        borderRadius: BorderRadius.circular(large ? 20 : 12),
        border: Border.all(color: moodData['color'].withOpacity(0.3)),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Text(
            moodData['emoji'],
            style: TextStyle(fontSize: large ? 32 : 20),
          ),
          SizedBox(width: large ? 12 : 8),
          Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            mainAxisSize: MainAxisSize.min,
            children: [
              Text(
                moodData['label'],
                style: TextStyle(
                  color: moodData['color'],
                  fontWeight: FontWeight.bold,
                  fontSize: large ? 18 : 14,
                ),
              ),
              if (trend != null)
                Row(
                  children: [
                    Icon(
                      trend == 'improving' ? Icons.trending_up :
                      trend == 'declining' ? Icons.trending_down :
                      Icons.trending_flat,
                      color: trend == 'improving' ? SovereignColors.green :
                             trend == 'declining' ? SovereignColors.red :
                             Colors.grey,
                      size: 14,
                    ),
                    const SizedBox(width: 4),
                    Text(
                      trend ?? 'stable',
                      style: TextStyle(color: Colors.grey[400], fontSize: 11),
                    ),
                  ],
                ),
            ],
          ),
        ],
      ),
    );
  }

  Map<String, dynamic> _getMoodData(String mood) {
    switch (mood.toLowerCase()) {
      case 'happy':
      case 'positive':
        return {'emoji': '😊', 'label': 'Happy', 'color': SovereignColors.moodHappy};
      case 'sad':
      case 'down':
        return {'emoji': '😔', 'label': 'Sad', 'color': SovereignColors.moodSad};
      case 'anxious':
      case 'worried':
        return {'emoji': '😰', 'label': 'Anxious', 'color': SovereignColors.moodAnxious};
      case 'angry':
      case 'frustrated':
        return {'emoji': '😤', 'label': 'Frustrated', 'color': SovereignColors.moodAngry};
      case 'calm':
      case 'peaceful':
        return {'emoji': '😌', 'label': 'Calm', 'color': SovereignColors.green};
      default:
        return {'emoji': '😐', 'label': 'Neutral', 'color': SovereignColors.moodNeutral};
    }
  }
}

// =============================================================================
// 5. RISK BADGE - Standalone risk level indicator
// =============================================================================
class RiskBadge extends StatelessWidget {
  final String riskLevel;
  final bool showIcon;
  final bool large;

  const RiskBadge({
    super.key,
    required this.riskLevel,
    this.showIcon = true,
    this.large = false,
  });

  @override
  Widget build(BuildContext context) {
    final data = _getRiskData(riskLevel);
    
    return Container(
      padding: EdgeInsets.symmetric(
        horizontal: large ? 16 : 10,
        vertical: large ? 8 : 4,
      ),
      decoration: BoxDecoration(
        color: data['color'].withOpacity(0.15),
        borderRadius: BorderRadius.circular(large ? 16 : 12),
        border: Border.all(color: data['color']),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          if (showIcon) ...[
            Icon(
              data['icon'],
              color: data['color'],
              size: large ? 20 : 14,
            ),
            SizedBox(width: large ? 8 : 4),
          ],
          Text(
            riskLevel.toUpperCase(),
            style: TextStyle(
              color: data['color'],
              fontWeight: FontWeight.bold,
              fontSize: large ? 14 : 10,
              letterSpacing: 1,
            ),
          ),
        ],
      ),
    );
  }

  Map<String, dynamic> _getRiskData(String level) {
    switch (level.toUpperCase()) {
      case 'LOW':
        return {'color': SovereignColors.riskLow, 'icon': Icons.check_circle};
      case 'MEDIUM':
        return {'color': SovereignColors.riskMedium, 'icon': Icons.warning};
      case 'HIGH':
        return {'color': SovereignColors.riskHigh, 'icon': Icons.error};
      case 'CRITICAL':
        return {'color': SovereignColors.riskCritical, 'icon': Icons.dangerous};
      default:
        return {'color': SovereignColors.riskLow, 'icon': Icons.help};
    }
  }
}

// =============================================================================
// 6. SESSION STATS CARD - Quick session overview
// =============================================================================
class SessionStatsCard extends StatelessWidget {
  final int totalSessions;
  final int breakthroughs;
  final int tokensUsed;
  final int tokensRemaining;

  const SessionStatsCard({
    super.key,
    required this.totalSessions,
    required this.breakthroughs,
    required this.tokensUsed,
    required this.tokensRemaining,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: SovereignColors.surface.withOpacity(0.5),
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: Colors.white10),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: const [
              Icon(Icons.insights, color: SovereignColors.gold, size: 20),
              SizedBox(width: 8),
              Text(
                "SESSION STATS",
                style: TextStyle(
                  color: SovereignColors.gold,
                  fontWeight: FontWeight.bold,
                  letterSpacing: 1.5,
                  fontSize: 12,
                ),
              ),
            ],
          ),
          const SizedBox(height: 16),
          Row(
            mainAxisAlignment: MainAxisAlignment.spaceAround,
            children: [
              _buildStat("Sessions", totalSessions.toString(), Icons.chat_bubble),
              _buildStat("Breakthroughs", breakthroughs.toString(), Icons.star),
              _buildStat("Tokens", "${(tokensRemaining / 1000).toStringAsFixed(1)}K", Icons.token),
            ],
          ),
          const SizedBox(height: 12),
          // Token usage bar
          Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                mainAxisAlignment: MainAxisAlignment.spaceBetween,
                children: [
                  Text("Token Usage", style: TextStyle(color: Colors.grey[400], fontSize: 11)),
                  Text(
                    "${tokensUsed.toString()} used",
                    style: TextStyle(color: Colors.grey[400], fontSize: 11),
                  ),
                ],
              ),
              const SizedBox(height: 4),
              ClipRRect(
                borderRadius: BorderRadius.circular(4),
                child: LinearProgressIndicator(
                  value: tokensUsed / (tokensUsed + tokensRemaining).clamp(1, double.infinity),
                  backgroundColor: Colors.white10,
                  valueColor: AlwaysStoppedAnimation(
                    tokensRemaining < 1000 ? SovereignColors.red : SovereignColors.cyan,
                  ),
                  minHeight: 6,
                ),
              ),
            ],
          ),
        ],
      ),
    );
  }

  Widget _buildStat(String label, String value, IconData icon) {
    return Column(
      children: [
        Icon(icon, color: Colors.grey[600], size: 20),
        const SizedBox(height: 4),
        Text(
          value,
          style: const TextStyle(
            color: Colors.white,
            fontWeight: FontWeight.bold,
            fontSize: 20,
            fontFamily: 'Courier',
          ),
        ),
        Text(label, style: TextStyle(color: Colors.grey[500], fontSize: 10)),
      ],
    );
  }
}

// =============================================================================
// 7. CLIENT BRIEF CARD - Coach view of client summary
// =============================================================================
class ClientBriefCard extends StatelessWidget {
  final Map<String, dynamic> brief;
  final VoidCallback? onTap;

  const ClientBriefCard({
    super.key,
    required this.brief,
    this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    final client = brief['client'] ?? {};
    final metrics = brief['metrics'] ?? {};
    final recentTopics = List<String>.from(brief['recent_topics'] ?? []);
    
    return GestureDetector(
      onTap: onTap,
      child: Container(
        margin: const EdgeInsets.only(bottom: 12),
        padding: const EdgeInsets.all(16),
        decoration: BoxDecoration(
          color: SovereignColors.card,
          borderRadius: BorderRadius.circular(16),
          border: Border.all(color: Colors.white10),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            // Header
            Row(
              children: [
                CircleAvatar(
                  backgroundColor: SovereignColors.purple.withOpacity(0.3),
                  child: Text(
                    (client['name'] ?? '?')[0].toUpperCase(),
                    style: const TextStyle(color: SovereignColors.purple, fontWeight: FontWeight.bold),
                  ),
                ),
                const SizedBox(width: 12),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        client['name'] ?? 'Unknown',
                        style: const TextStyle(
                          color: Colors.white,
                          fontWeight: FontWeight.bold,
                          fontSize: 16,
                        ),
                      ),
                      Text(
                        "Since ${client['joined_date'] ?? 'Unknown'}",
                        style: TextStyle(color: Colors.grey[500], fontSize: 11),
                      ),
                    ],
                  ),
                ),
                RiskBadge(riskLevel: metrics['risk_level'] ?? 'LOW'),
              ],
            ),
            
            const SizedBox(height: 16),
            
            // Quick metrics
            Row(
              mainAxisAlignment: MainAxisAlignment.spaceAround,
              children: [
                _buildQuickMetric("Text Sent.", metrics['text_sentiment_v1'] ?? metrics['C_emo'] ?? metrics['coherence'] ?? 0.5, SovereignColors.cyan),
                _buildQuickMetric("GAP", metrics['GAP'] ?? metrics['growth'] ?? metrics['growth_potential'] ?? 0.3, SovereignColors.purple),
                _buildQuickMetric("Engage", metrics['engagement'] ?? metrics['engage'] ?? 0.5, SovereignColors.green),
              ],
            ),
            
            const SizedBox(height: 12),
            
            // Mood
            Row(
              children: [
                MoodIndicator(
                  mood: metrics['mood_current'] ?? 'neutral',
                  trend: metrics['mood_trend'],
                ),
                const Spacer(),
                Text(
                  "${client['total_sessions'] ?? 0} sessions",
                  style: TextStyle(color: Colors.grey[400], fontSize: 12),
                ),
              ],
            ),
            
            if (recentTopics.isNotEmpty) ...[
              const SizedBox(height: 12),
              Wrap(
                spacing: 6,
                runSpacing: 6,
                children: recentTopics.take(4).map((topic) => Container(
                  padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
                  decoration: BoxDecoration(
                    color: Colors.white.withOpacity(0.05),
                    borderRadius: BorderRadius.circular(12),
                  ),
                  child: Text(
                    topic,
                    style: TextStyle(color: Colors.grey[400], fontSize: 10),
                  ),
                )).toList(),
              ),
            ],
          ],
        ),
      ),
    );
  }

  Widget _buildQuickMetric(String label, dynamic value, Color color) {
    final double v = _parseDouble(value);
    return Column(
      children: [
        Text(
          "${(v * 100).toInt()}%",
          style: TextStyle(
            color: color,
            fontWeight: FontWeight.bold,
            fontSize: 16,
            fontFamily: 'Courier',
          ),
        ),
        Text(label, style: TextStyle(color: Colors.grey[500], fontSize: 10)),
      ],
    );
  }

  double _parseDouble(dynamic value) {
    if (value == null) return 0.0;
    if (value is double) return value;
    if (value is int) return value.toDouble();
    if (value is String) {
      final cleaned = value.replaceAll('%', '');
      final parsed = double.tryParse(cleaned) ?? 0.0;
      return parsed > 1 ? parsed / 100 : parsed;
    }
    return 0.0;
  }
}

// =============================================================================
// 8. CRISIS ALERT CARD - Admin crisis watchlist item
// =============================================================================
class CrisisAlertCard extends StatelessWidget {
  final Map<String, dynamic> alert;
  final VoidCallback? onResolve;
  final VoidCallback? onViewProfile;

  const CrisisAlertCard({
    super.key,
    required this.alert,
    this.onResolve,
    this.onViewProfile,
  });

  @override
  Widget build(BuildContext context) {
    final bool resolved = alert['resolved'] ?? false;
    
    return Container(
      margin: const EdgeInsets.only(bottom: 12),
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: resolved 
            ? SovereignColors.surface.withOpacity(0.3)
            : SovereignColors.red.withOpacity(0.1),
        borderRadius: BorderRadius.circular(16),
        border: Border.all(
          color: resolved ? Colors.white10 : SovereignColors.red.withOpacity(0.5),
        ),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Icon(
                resolved ? Icons.check_circle : Icons.warning,
                color: resolved ? SovereignColors.green : SovereignColors.red,
                size: 24,
              ),
              const SizedBox(width: 12),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      alert['user_name'] ?? 'Unknown User',
                      style: TextStyle(
                        color: resolved ? Colors.grey : Colors.white,
                        fontWeight: FontWeight.bold,
                        fontSize: 16,
                      ),
                    ),
                    Text(
                      alert['timestamp'] ?? '',
                      style: TextStyle(color: Colors.grey[500], fontSize: 11),
                    ),
                  ],
                ),
              ),
              if (!resolved)
                RiskBadge(riskLevel: 'CRITICAL', large: true),
            ],
          ),
          
          const SizedBox(height: 12),
          
          // Trigger
          Container(
            padding: const EdgeInsets.all(12),
            decoration: BoxDecoration(
              color: Colors.black.withOpacity(0.3),
              borderRadius: BorderRadius.circular(8),
            ),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  "TRIGGER: ${alert['trigger'] ?? 'Unknown'}",
                  style: TextStyle(
                    color: SovereignColors.red.withOpacity(0.8),
                    fontWeight: FontWeight.bold,
                    fontSize: 11,
                  ),
                ),
                const SizedBox(height: 4),
                Text(
                  alert['context'] ?? 'No context available',
                  style: TextStyle(color: Colors.grey[400], fontSize: 12),
                  maxLines: 3,
                  overflow: TextOverflow.ellipsis,
                ),
              ],
            ),
          ),
          
          if (!resolved) ...[
            const SizedBox(height: 12),
            Row(
              children: [
                Expanded(
                  child: OutlinedButton.icon(
                    onPressed: onViewProfile,
                    icon: const Icon(Icons.person, size: 16),
                    label: const Text("VIEW PROFILE"),
                    style: OutlinedButton.styleFrom(
                      foregroundColor: Colors.white70,
                      side: const BorderSide(color: Colors.white24),
                    ),
                  ),
                ),
                const SizedBox(width: 12),
                Expanded(
                  child: ElevatedButton.icon(
                    onPressed: onResolve,
                    icon: const Icon(Icons.check, size: 16),
                    label: const Text("RESOLVE"),
                    style: ElevatedButton.styleFrom(
                      backgroundColor: SovereignColors.green,
                      foregroundColor: Colors.black,
                    ),
                  ),
                ),
              ],
            ),
          ],
        ],
      ),
    );
  }
}

// =============================================================================
// 9. METRICS SCREEN - Full page metrics view
// =============================================================================
class MetricsScreen extends StatefulWidget {
  final Map<String, dynamic> profile;
  final String username;
  final String password;

  const MetricsScreen({
    super.key,
    required this.profile,
    required this.username,
    required this.password,
  });

  @override
  State<MetricsScreen> createState() => _MetricsScreenState();
}

class _MetricsScreenState extends State<MetricsScreen> {
  Map<String, dynamic>? _metrics;
  List<dynamic> _moodHistory = [];
  bool _isLoading = true;

  @override
  void initState() {
    super.initState();
    _loadMetrics();
  }

  void _loadMetrics() {
    // In production, fetch from WebSocket
    // For now, use profile data
    setState(() {
      _metrics = {
        'C_emo': widget.profile['C_emo'] ?? 0.5,
        'GAP': widget.profile['GAP'] ?? 0.3,
        'Quantum': widget.profile['Quantum'] ?? 0.5,
        'anxiety_level': widget.profile['anxiety_level'] ?? 0,
        'stress_level': widget.profile['stress_level'] ?? 0,
        'engagement': widget.profile['engagement'] ?? 0.5,
        'risk_level': widget.profile['risk_level'] ?? 'LOW',
        'mood_current': widget.profile['mood_current'] ?? 'neutral',
        'mood_trend': widget.profile['mood_trend'] ?? 'stable',
      };
      _moodHistory = widget.profile['mood_history'] ?? [];
      _isLoading = false;
    });
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: SovereignColors.background,
      appBar: AppBar(
        title: const Text(
          "MY METRICS",
          style: TextStyle(
            fontFamily: 'Courier',
            color: SovereignColors.cyan,
            letterSpacing: 2,
          ),
        ),
        backgroundColor: Colors.transparent,
        elevation: 0,
        leading: IconButton(
          icon: const Icon(Icons.arrow_back, color: Colors.white70),
          onPressed: () => Navigator.pop(context),
        ),
      ),
      body: _isLoading
          ? const Center(child: CircularProgressIndicator(color: SovereignColors.cyan))
          : SingleChildScrollView(
              padding: const EdgeInsets.all(16),
              child: Column(
                children: [
                  // Current mood
                  Row(
                    children: [
                      Expanded(
                        child: MoodIndicator(
                          mood: _metrics?['mood_current'] ?? 'neutral',
                          trend: _metrics?['mood_trend'],
                          large: true,
                        ),
                      ),
                    ],
                  ),
                  
                  const SizedBox(height: 20),
                  
                  // Nevedal metrics
                  NevedalMetricsGrid(metrics: _metrics ?? {}),
                  
                  const SizedBox(height: 20),
                  
                  // Mood history chart
                  MoodHistoryChart(moodHistory: _moodHistory, height: 180),
                  
                  const SizedBox(height: 20),
                  
                  // Session stats
                  SessionStatsCard(
                    totalSessions: widget.profile['total_sessions_count'] ?? 0,
                    breakthroughs: widget.profile['breakthrough_count'] ?? 0,
                    tokensUsed: widget.profile['token_usage_month'] ?? 0,
                    tokensRemaining: widget.profile['token_balance'] ?? 10000,
                  ),
                ],
              ),
            ),
    );
  }
}
