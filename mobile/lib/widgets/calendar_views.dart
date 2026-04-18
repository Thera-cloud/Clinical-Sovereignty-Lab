/// Calendar view widgets — Month / Week / Day / List / Timeline + Toolbar.
///
/// Used by both the client schedule screen (`main.dart`) and the coach
/// schedule tab (`updated_screens.dart`). All views consume a normalized
/// `CalendarEvent` list so callers can plug in Sanctuary sessions, Google
/// Calendar mirrored events, or Zoom meetings.
library;

import 'package:flutter/material.dart';

/// Normalized event model for all calendar views.
class CalendarEvent {
  final String id;
  final DateTime start;
  final DateTime end;
  final String title;
  final String subtitle;
  final Color color;
  final String tooltip;
  final String source; // 'sanctuary' | 'google' | 'zoom'
  final Object? raw;

  const CalendarEvent({
    required this.id,
    required this.start,
    required this.end,
    required this.title,
    this.subtitle = '',
    this.color = const Color(0xFFC9A962),
    this.tooltip = '',
    this.source = 'sanctuary',
    this.raw,
  });

  Duration get duration => end.difference(start);
}

/// Currently active calendar view.
enum CalendarView { month, week, day, list, timeline }

/// Toolbar with view switcher + Today/prev/next nav.
class CalendarToolbar extends StatelessWidget {
  final CalendarView view;
  final DateTime focusedDate;
  final ValueChanged<CalendarView> onViewChanged;
  final ValueChanged<DateTime> onDateChanged;

  const CalendarToolbar({
    super.key,
    required this.view,
    required this.focusedDate,
    required this.onViewChanged,
    required this.onDateChanged,
  });

  static const _gold = Color(0xFFC9A962);
  static const _goldDim = Color(0xFF8B7355);
  static const _chamber = Color(0xFF0A0A0A);

  void _step(int direction) {
    DateTime next;
    switch (view) {
      case CalendarView.month:
        next = DateTime(
          focusedDate.year,
          focusedDate.month + direction,
          1,
        );
        break;
      case CalendarView.week:
        next = focusedDate.add(Duration(days: 7 * direction));
        break;
      case CalendarView.day:
        next = focusedDate.add(Duration(days: direction));
        break;
      case CalendarView.list:
      case CalendarView.timeline:
        next = focusedDate.add(Duration(days: 7 * direction));
        break;
    }
    onDateChanged(next);
  }

  String _label() {
    const months = [
      'January', 'February', 'March', 'April', 'May', 'June',
      'July', 'August', 'September', 'October', 'November', 'December',
    ];
    final m = months[focusedDate.month - 1];
    switch (view) {
      case CalendarView.month:
      case CalendarView.list:
        return '$m ${focusedDate.year}';
      case CalendarView.week:
      case CalendarView.timeline:
        final start = focusedDate.subtract(Duration(days: focusedDate.weekday % 7));
        final end = start.add(const Duration(days: 6));
        return '${start.month}/${start.day} – ${end.month}/${end.day}, ${focusedDate.year}';
      case CalendarView.day:
        return '$m ${focusedDate.day}, ${focusedDate.year}';
    }
  }

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
      decoration: BoxDecoration(
        color: _chamber,
        border: Border(
          bottom: BorderSide(color: _gold.withOpacity(0.25)),
        ),
      ),
      child: Wrap(
        spacing: 8,
        runSpacing: 8,
        crossAxisAlignment: WrapCrossAlignment.center,
        children: [
          IconButton(
            icon: const Icon(Icons.chevron_left, color: _gold),
            tooltip: 'Previous',
            onPressed: () => _step(-1),
          ),
          TextButton(
            onPressed: () => onDateChanged(DateTime.now()),
            style: TextButton.styleFrom(
              foregroundColor: _gold,
              side: const BorderSide(color: _goldDim),
              padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
            ),
            child: const Text('Today'),
          ),
          IconButton(
            icon: const Icon(Icons.chevron_right, color: _gold),
            tooltip: 'Next',
            onPressed: () => _step(1),
          ),
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 8),
            child: Text(
              _label(),
              style: const TextStyle(
                color: _gold,
                fontSize: 14,
                fontWeight: FontWeight.w600,
              ),
            ),
          ),
          const SizedBox(width: 12),
          ToggleButtons(
            isSelected: CalendarView.values.map((v) => v == view).toList(),
            onPressed: (i) => onViewChanged(CalendarView.values[i]),
            color: _goldDim,
            selectedColor: _chamber,
            fillColor: _gold,
            borderColor: _goldDim,
            selectedBorderColor: _gold,
            borderRadius: BorderRadius.circular(6),
            constraints: const BoxConstraints(minHeight: 32, minWidth: 64),
            children: const [
              Text('Month'),
              Text('Week'),
              Text('Day'),
              Text('List'),
              Text('Timeline'),
            ],
          ),
        ],
      ),
    );
  }
}

const _gold = Color(0xFFC9A962);
const _goldDim = Color(0xFF8B7355);
const _bg = Color(0xFF050505);
const _chamber = Color(0xFF0A0A0A);
const _elevated = Color(0xFF111111);

/// Helper: list of events overlapping a given day.
List<CalendarEvent> _eventsOnDay(List<CalendarEvent> events, DateTime day) {
  final dayStart = DateTime(day.year, day.month, day.day);
  final dayEnd = dayStart.add(const Duration(days: 1));
  return events
      .where((e) => e.start.isBefore(dayEnd) && e.end.isAfter(dayStart))
      .toList();
}

/// Week view — 7 columns, hour rows.
class CalendarWeekGrid extends StatelessWidget {
  final DateTime focusedDate;
  final List<CalendarEvent> events;
  final void Function(CalendarEvent) onEventTap;

  const CalendarWeekGrid({
    super.key,
    required this.focusedDate,
    required this.events,
    required this.onEventTap,
  });

  @override
  Widget build(BuildContext context) {
    final start = focusedDate.subtract(Duration(days: focusedDate.weekday % 7));
    final days = List.generate(7, (i) => start.add(Duration(days: i)));
    const dayLabels = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
    return Column(
      children: [
        Row(
          children: [
            const SizedBox(width: 48),
            for (int i = 0; i < 7; i++)
              Expanded(
                child: Container(
                  padding: const EdgeInsets.symmetric(vertical: 6),
                  alignment: Alignment.center,
                  decoration: BoxDecoration(
                    color: _chamber,
                    border: Border(
                      bottom: BorderSide(color: _gold.withOpacity(0.25)),
                    ),
                  ),
                  child: Text(
                    '${dayLabels[i]}\n${days[i].month}/${days[i].day}',
                    textAlign: TextAlign.center,
                    style: const TextStyle(color: _gold, fontSize: 11),
                  ),
                ),
              ),
          ],
        ),
        Expanded(
          child: SingleChildScrollView(
            child: SizedBox(
              height: 24 * 36.0,
              child: Row(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  Column(
                    children: List.generate(24, (h) {
                      return Container(
                        height: 36,
                        width: 48,
                        alignment: Alignment.topRight,
                        padding: const EdgeInsets.only(right: 4, top: 2),
                        child: Text(
                          '${h.toString().padLeft(2, '0')}:00',
                          style: const TextStyle(color: _goldDim, fontSize: 9),
                        ),
                      );
                    }),
                  ),
                  for (final day in days)
                    Expanded(
                      child: _DayColumn(
                        day: day,
                        events: _eventsOnDay(events, day),
                        onEventTap: onEventTap,
                      ),
                    ),
                ],
              ),
            ),
          ),
        ),
      ],
    );
  }
}

/// Day view — single-column hour grid with events positioned by start time.
class CalendarDayGrid extends StatelessWidget {
  final DateTime focusedDate;
  final List<CalendarEvent> events;
  final void Function(CalendarEvent) onEventTap;

  const CalendarDayGrid({
    super.key,
    required this.focusedDate,
    required this.events,
    required this.onEventTap,
  });

  @override
  Widget build(BuildContext context) {
    final dayEvents = _eventsOnDay(events, focusedDate);
    return SingleChildScrollView(
      child: SizedBox(
        height: 24 * 48.0,
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Column(
              children: List.generate(24, (h) {
                return Container(
                  height: 48,
                  width: 56,
                  alignment: Alignment.topRight,
                  padding: const EdgeInsets.only(right: 6, top: 2),
                  child: Text(
                    '${h.toString().padLeft(2, '0')}:00',
                    style: const TextStyle(color: _goldDim, fontSize: 10),
                  ),
                );
              }),
            ),
            Expanded(
              child: _DayColumn(
                day: focusedDate,
                events: dayEvents,
                onEventTap: onEventTap,
                hourHeight: 48,
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _DayColumn extends StatelessWidget {
  final DateTime day;
  final List<CalendarEvent> events;
  final void Function(CalendarEvent) onEventTap;
  final double hourHeight;

  const _DayColumn({
    required this.day,
    required this.events,
    required this.onEventTap,
    this.hourHeight = 36,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      decoration: BoxDecoration(
        border: Border(left: BorderSide(color: _gold.withOpacity(0.15))),
      ),
      child: Stack(
        children: [
          Column(
            children: List.generate(24, (h) {
              return Container(
                height: hourHeight,
                decoration: BoxDecoration(
                  border: Border(
                    bottom: BorderSide(
                      color: _gold.withOpacity(0.08),
                    ),
                  ),
                ),
              );
            }),
          ),
          for (final ev in events) _positionedEvent(ev),
        ],
      ),
    );
  }

  Widget _positionedEvent(CalendarEvent ev) {
    final dayStart = DateTime(day.year, day.month, day.day);
    final startMin = ev.start.isBefore(dayStart)
        ? 0
        : ev.start.difference(dayStart).inMinutes;
    final endMin = ev.end
        .difference(dayStart)
        .inMinutes
        .clamp(startMin + 15, 24 * 60);
    final top = (startMin / 60.0) * hourHeight;
    final height = ((endMin - startMin) / 60.0) * hourHeight;
    return Positioned(
      top: top,
      left: 2,
      right: 2,
      height: height < 18 ? 18 : height,
      child: GestureDetector(
        onTap: () => onEventTap(ev),
        child: Tooltip(
          message: ev.tooltip.isEmpty ? ev.title : ev.tooltip,
          child: Container(
            padding: const EdgeInsets.symmetric(horizontal: 4, vertical: 2),
            decoration: BoxDecoration(
              color: ev.color.withOpacity(0.85),
              borderRadius: BorderRadius.circular(4),
              border: Border.all(color: ev.color),
            ),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  ev.title,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: const TextStyle(
                    color: Colors.white,
                    fontSize: 10,
                    fontWeight: FontWeight.w600,
                  ),
                ),
                if (ev.subtitle.isNotEmpty)
                  Text(
                    ev.subtitle,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: const TextStyle(color: Colors.white70, fontSize: 9),
                  ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

/// List view — flat chronological list of upcoming events from focusedDate.
class CalendarListView extends StatelessWidget {
  final DateTime focusedDate;
  final List<CalendarEvent> events;
  final void Function(CalendarEvent) onEventTap;
  final int daysWindow;

  const CalendarListView({
    super.key,
    required this.focusedDate,
    required this.events,
    required this.onEventTap,
    this.daysWindow = 30,
  });

  @override
  Widget build(BuildContext context) {
    final start = DateTime(focusedDate.year, focusedDate.month, focusedDate.day);
    final end = start.add(Duration(days: daysWindow));
    final upcoming = events
        .where((e) => e.end.isAfter(start) && e.start.isBefore(end))
        .toList()
      ..sort((a, b) => a.start.compareTo(b.start));
    if (upcoming.isEmpty) {
      return const Center(
        child: Padding(
          padding: EdgeInsets.all(24),
          child: Text(
            'No events in the next 30 days.',
            style: TextStyle(color: _goldDim, fontSize: 13),
          ),
        ),
      );
    }
    return ListView.separated(
      padding: const EdgeInsets.all(12),
      itemCount: upcoming.length,
      separatorBuilder: (_, __) => const SizedBox(height: 8),
      itemBuilder: (context, i) {
        final ev = upcoming[i];
        return InkWell(
          onTap: () => onEventTap(ev),
          child: Container(
            padding: const EdgeInsets.all(12),
            decoration: BoxDecoration(
              color: _elevated,
              borderRadius: BorderRadius.circular(8),
              border: Border(left: BorderSide(color: ev.color, width: 4)),
            ),
            child: Row(
              children: [
                Container(
                  width: 56,
                  alignment: Alignment.center,
                  child: Column(
                    children: [
                      Text(
                        _monthShort(ev.start.month),
                        style: const TextStyle(color: _goldDim, fontSize: 10),
                      ),
                      Text(
                        '${ev.start.day}',
                        style: const TextStyle(
                          color: _gold,
                          fontSize: 22,
                          fontWeight: FontWeight.w600,
                        ),
                      ),
                      Text(
                        _weekdayShort(ev.start.weekday),
                        style: const TextStyle(color: _goldDim, fontSize: 10),
                      ),
                    ],
                  ),
                ),
                const SizedBox(width: 12),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        ev.title,
                        style: const TextStyle(
                          color: Colors.white,
                          fontSize: 14,
                          fontWeight: FontWeight.w600,
                        ),
                      ),
                      const SizedBox(height: 2),
                      Text(
                        '${_fmtTime(ev.start)} – ${_fmtTime(ev.end)}',
                        style: const TextStyle(color: _goldDim, fontSize: 12),
                      ),
                      if (ev.subtitle.isNotEmpty) ...[
                        const SizedBox(height: 2),
                        Text(
                          ev.subtitle,
                          style: const TextStyle(color: Colors.white70, fontSize: 12),
                        ),
                      ],
                    ],
                  ),
                ),
                if (ev.source != 'sanctuary')
                  Container(
                    padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
                    decoration: BoxDecoration(
                      color: _bg,
                      borderRadius: BorderRadius.circular(4),
                      border: Border.all(color: ev.color.withOpacity(0.6)),
                    ),
                    child: Text(
                      ev.source.toUpperCase(),
                      style: TextStyle(color: ev.color, fontSize: 9),
                    ),
                  ),
              ],
            ),
          ),
        );
      },
    );
  }
}

/// Timeline view — horizontal stripe per day with events as bars.
class CalendarTimelineView extends StatelessWidget {
  final DateTime focusedDate;
  final List<CalendarEvent> events;
  final void Function(CalendarEvent) onEventTap;
  final int daysWindow;

  const CalendarTimelineView({
    super.key,
    required this.focusedDate,
    required this.events,
    required this.onEventTap,
    this.daysWindow = 7,
  });

  @override
  Widget build(BuildContext context) {
    final start = focusedDate.subtract(Duration(days: focusedDate.weekday % 7));
    final days = List.generate(daysWindow, (i) => start.add(Duration(days: i)));
    return ListView.builder(
      padding: const EdgeInsets.all(8),
      itemCount: days.length,
      itemBuilder: (context, i) {
        final day = days[i];
        final dayEvents = _eventsOnDay(events, day);
        return Container(
          margin: const EdgeInsets.symmetric(vertical: 4),
          padding: const EdgeInsets.all(8),
          decoration: BoxDecoration(
            color: _elevated,
            borderRadius: BorderRadius.circular(6),
          ),
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              SizedBox(
                width: 64,
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      _weekdayShort(day.weekday),
                      style: const TextStyle(color: _goldDim, fontSize: 11),
                    ),
                    Text(
                      '${day.month}/${day.day}',
                      style: const TextStyle(
                        color: _gold,
                        fontSize: 14,
                        fontWeight: FontWeight.w600,
                      ),
                    ),
                  ],
                ),
              ),
              Expanded(
                child: SizedBox(
                  height: 32,
                  child: Stack(
                    children: [
                      Positioned.fill(
                        child: Container(
                          decoration: BoxDecoration(
                            color: _bg,
                            borderRadius: BorderRadius.circular(4),
                          ),
                        ),
                      ),
                      ...dayEvents.map((ev) {
                        final dayStart = DateTime(day.year, day.month, day.day);
                        final startMin = ev.start.isBefore(dayStart)
                            ? 0
                            : ev.start.difference(dayStart).inMinutes;
                        final endMin = ev.end
                            .difference(dayStart)
                            .inMinutes
                            .clamp(startMin + 15, 24 * 60);
                        return LayoutBuilder(builder: (ctx, constraints) {
                          final w = constraints.maxWidth;
                          final left = (startMin / (24 * 60)) * w;
                          final width = ((endMin - startMin) / (24 * 60)) * w;
                          return Positioned(
                            left: left,
                            top: 4,
                            bottom: 4,
                            width: width < 4 ? 4 : width,
                            child: GestureDetector(
                              onTap: () => onEventTap(ev),
                              child: Tooltip(
                                message: ev.tooltip.isEmpty ? ev.title : ev.tooltip,
                                child: Container(
                                  padding: const EdgeInsets.symmetric(horizontal: 4),
                                  decoration: BoxDecoration(
                                    color: ev.color.withOpacity(0.85),
                                    borderRadius: BorderRadius.circular(3),
                                  ),
                                  child: Text(
                                    ev.title,
                                    maxLines: 1,
                                    overflow: TextOverflow.ellipsis,
                                    style: const TextStyle(
                                      color: Colors.white,
                                      fontSize: 10,
                                      fontWeight: FontWeight.w600,
                                    ),
                                  ),
                                ),
                              ),
                            ),
                          );
                        });
                      }),
                    ],
                  ),
                ),
              ),
            ],
          ),
        );
      },
    );
  }
}

String _monthShort(int m) {
  const arr = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
               'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  return arr[(m - 1).clamp(0, 11)];
}

String _weekdayShort(int wd) {
  const arr = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
  return arr[(wd - 1).clamp(0, 6)];
}

String _fmtTime(DateTime t) {
  final h = t.hour;
  final m = t.minute.toString().padLeft(2, '0');
  final period = h >= 12 ? 'PM' : 'AM';
  final hh = ((h + 11) % 12) + 1;
  return '$hh:$m $period';
}
