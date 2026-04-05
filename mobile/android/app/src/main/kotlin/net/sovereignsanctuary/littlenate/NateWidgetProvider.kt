package net.sovereignsanctuary.littlenate

import android.appwidget.AppWidgetManager
import android.appwidget.AppWidgetProvider
import android.content.Context
import android.content.SharedPreferences
import android.app.PendingIntent
import android.content.Intent
import android.graphics.Color
import android.net.Uri
import android.widget.RemoteViews

class NateWidgetProvider : AppWidgetProvider() {

    override fun onUpdate(context: Context, manager: AppWidgetManager, ids: IntArray) {
        for (id in ids) {
            updateWidget(context, manager, id)
        }
    }

    companion object {
        private fun getPrefs(ctx: Context): SharedPreferences {
            return ctx.getSharedPreferences("HomeWidgetPreferences", Context.MODE_PRIVATE)
        }

        fun updateWidget(ctx: Context, manager: AppWidgetManager, id: Int) {
            val prefs = getPrefs(ctx)
            val primary = prefs.getString("widget_primary_text", "Breathe") ?: "Breathe"
            val secondary = prefs.getString("widget_secondary_text", "") ?: ""
            val bgHex = prefs.getString("widget_background_color", "#1a2332") ?: "#1a2332"
            val action = prefs.getString("widget_action", "open_chat") ?: "open_chat"
            val actionId = prefs.getString("widget_action_id", "") ?: ""

            val views = RemoteViews(ctx.packageName, R.layout.nate_widget_small)
            views.setTextViewText(R.id.widget_primary_text, primary)
            views.setTextViewText(R.id.widget_secondary_text, secondary)

            try {
                views.setInt(R.id.widget_root, "setBackgroundColor", Color.parseColor(bgHex))
            } catch (_: Exception) {
                views.setInt(R.id.widget_root, "setBackgroundColor", Color.parseColor("#1a2332"))
            }

            val intent = Intent(ctx, MainActivity::class.java).apply {
                data = Uri.parse("littlenate://widget?action=$action&id=$actionId")
                flags = Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP
            }
            val pending = PendingIntent.getActivity(
                ctx, 0, intent,
                PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
            )
            views.setOnClickPendingIntent(R.id.widget_root, pending)

            manager.updateAppWidget(id, views)
        }
    }
}

class NateWidgetMediumProvider : AppWidgetProvider() {

    override fun onUpdate(context: Context, manager: AppWidgetManager, ids: IntArray) {
        for (id in ids) {
            updateWidget(context, manager, id)
        }
    }

    companion object {
        fun updateWidget(ctx: Context, manager: AppWidgetManager, id: Int) {
            val prefs = ctx.getSharedPreferences("HomeWidgetPreferences", Context.MODE_PRIVATE)
            val primary = prefs.getString("widget_primary_text", "Breathe") ?: "Breathe"
            val secondary = prefs.getString("widget_secondary_text", "") ?: ""
            val bgHex = prefs.getString("widget_background_color", "#1a2332") ?: "#1a2332"
            val action = prefs.getString("widget_action", "open_chat") ?: "open_chat"
            val actionId = prefs.getString("widget_action_id", "") ?: ""

            val views = RemoteViews(ctx.packageName, R.layout.nate_widget_medium)
            views.setTextViewText(R.id.widget_primary_text, primary)
            views.setTextViewText(R.id.widget_secondary_text, secondary)

            try {
                views.setInt(R.id.widget_root, "setBackgroundColor", Color.parseColor(bgHex))
            } catch (_: Exception) {
                views.setInt(R.id.widget_root, "setBackgroundColor", Color.parseColor("#1a2332"))
            }

            val intent = Intent(ctx, MainActivity::class.java).apply {
                data = Uri.parse("littlenate://widget?action=$action&id=$actionId")
                flags = Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP
            }
            val pending = PendingIntent.getActivity(
                ctx, 1, intent,
                PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
            )
            views.setOnClickPendingIntent(R.id.widget_root, pending)

            manager.updateAppWidget(id, views)
        }
    }
}
