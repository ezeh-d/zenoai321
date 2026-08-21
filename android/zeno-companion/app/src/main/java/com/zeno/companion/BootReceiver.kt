package com.zeno.companion

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.provider.Settings

class BootReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent?) {
        if (intent?.action != Intent.ACTION_BOOT_COMPLETED) return
        val enabled = context.getSharedPreferences("zeno_overlay", Context.MODE_PRIVATE)
            .getBoolean("start_on_boot", false)
        if (!enabled || !Settings.canDrawOverlays(context) || SecureStore(context).load() == null) return
        try {
            context.startForegroundService(Intent(context, OverlayService::class.java))
        } catch (_: RuntimeException) {
            // Android background-start policy remains authoritative. The owner
            // can always restart ZENO explicitly from the launcher.
        }
    }
}
