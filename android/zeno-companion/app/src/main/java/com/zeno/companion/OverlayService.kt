package com.zeno.companion

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Intent
import android.content.pm.ServiceInfo
import android.graphics.Color
import android.graphics.PixelFormat
import android.graphics.drawable.GradientDrawable
import android.os.Build
import android.os.IBinder
import android.provider.Settings
import android.view.Gravity
import android.view.MotionEvent
import android.view.View
import android.view.WindowManager
import android.widget.Button
import android.widget.LinearLayout
import android.widget.TextView
import org.json.JSONObject
import java.util.concurrent.Executors
import java.util.concurrent.ScheduledExecutorService
import java.util.concurrent.TimeUnit
import kotlin.math.abs

class OverlayService : Service() {
    private lateinit var windowManager: WindowManager
    private var overlay: LinearLayout? = null
    private var orb: TextView? = null
    private var detail: LinearLayout? = null
    private var layout: WindowManager.LayoutParams? = null
    private var poller: ScheduledExecutorService? = null
    private var lastHeartbeat = 0L

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onCreate() {
        super.onCreate()
        current = this
        createNotificationChannel()
        val notification = notification("ZENO is ready")
        if (Build.VERSION.SDK_INT >= 34) {
            startForeground(NOTIFICATION_ID, notification, ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE)
        } else {
            startForeground(NOTIFICATION_ID, notification)
        }
        windowManager = getSystemService(WINDOW_SERVICE) as WindowManager
        ensureOverlay()
        startPolling()
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        ensureOverlay()
        return START_STICKY
    }

    override fun onDestroy() {
        poller?.shutdownNow()
        poller = null
        removeOverlay()
        if (current === this) current = null
        super.onDestroy()
    }

    private fun dp(value: Int) = (value * resources.displayMetrics.density).toInt()

    private fun createNotificationChannel() {
        val manager = getSystemService(NOTIFICATION_SERVICE) as NotificationManager
        manager.createNotificationChannel(
            NotificationChannel(CHANNEL_ID, "ZENO active orb", NotificationManager.IMPORTANCE_LOW).apply {
                description = "Visible while the owner-enabled ZENO overlay is active"
                setShowBadge(false)
            }
        )
    }

    private fun notification(message: String): Notification {
        val pending = PendingIntent.getActivity(
            this, 0, Intent(this, MainActivity::class.java),
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )
        return Notification.Builder(this, CHANNEL_ID)
            .setSmallIcon(com.zeno.companion.R.drawable.ic_zeno)
            .setContentTitle("ZENO Companion active")
            .setContentText(message.take(80))
            .setContentIntent(pending)
            .setOngoing(true)
            .setCategory(Notification.CATEGORY_SERVICE)
            .build()
    }

    private fun updateNotification(message: String) {
        (getSystemService(NOTIFICATION_SERVICE) as NotificationManager)
            .notify(NOTIFICATION_ID, notification(message))
    }

    private fun orbBackground(colour: Int) = GradientDrawable().apply {
        shape = GradientDrawable.OVAL
        setColor(Color.rgb(7, 18, 38))
        setStroke(dp(3), colour)
    }

    private fun panelBackground() = GradientDrawable().apply {
        cornerRadius = dp(18).toFloat()
        setColor(Color.argb(245, 7, 18, 38))
        setStroke(dp(1), Color.rgb(45, 89, 126))
    }

    private fun ensureOverlay() {
        if (!Settings.canDrawOverlays(this)) {
            publishState("OVERLAY PERMISSION NEEDED")
            return
        }
        if (overlay?.isAttachedToWindow == true) {
            clampPosition()
            return
        }
        removeOverlay()
        val preferences = getSharedPreferences("zeno_overlay", MODE_PRIVATE)
        layout = WindowManager.LayoutParams(
            WindowManager.LayoutParams.WRAP_CONTENT,
            WindowManager.LayoutParams.WRAP_CONTENT,
            WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY,
            WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE or
                WindowManager.LayoutParams.FLAG_NOT_TOUCH_MODAL,
            PixelFormat.TRANSLUCENT
        ).apply {
            gravity = Gravity.TOP or Gravity.START
            x = preferences.getInt("x", resources.displayMetrics.widthPixels - dp(78))
            y = preferences.getInt("y", resources.displayMetrics.heightPixels / 3)
        }

        val root = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
            setPadding(dp(6), dp(6), dp(6), dp(6))
        }
        orb = TextView(this).apply {
            text = "Z"
            textSize = 24f
            gravity = Gravity.CENTER
            setTextColor(Color.rgb(255, 244, 196))
            background = orbBackground(Color.rgb(66, 217, 255))
            layoutParams = LinearLayout.LayoutParams(dp(62), dp(62))
        }
        detail = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            visibility = View.GONE
            background = panelBackground()
            setPadding(dp(12), dp(8), dp(12), dp(8))
            addView(TextView(this@OverlayService).apply {
                text = "ZENO • READY"
                setTextColor(Color.WHITE)
                textSize = 13f
                tag = STATE_TEXT_TAG
            })
            addView(Button(this@OverlayService).apply {
                text = "Open ZENO"
                isAllCaps = false
                setOnClickListener {
                    startActivity(Intent(this@OverlayService, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
                }
            })
            addView(Button(this@OverlayService).apply {
                text = "Stop orb"
                isAllCaps = false
                setOnClickListener { stopSelf() }
            })
        }
        root.addView(orb)
        root.addView(detail)
        overlay = root
        installDragListener()
        try {
            windowManager.addView(root, layout)
            clampPosition()
            publishState(if (ZenoAccessibilityService.available()) "READY" else "TAP • CONTROLS OFF")
        } catch (_: Exception) {
            overlay = null
            publishState("OVERLAY ERROR")
        }
    }

    private fun installDragListener() {
        var downX = 0
        var downY = 0
        var touchX = 0f
        var touchY = 0f
        orb?.setOnTouchListener { _, event ->
            val params = layout ?: return@setOnTouchListener false
            when (event.actionMasked) {
                MotionEvent.ACTION_DOWN -> {
                    downX = params.x
                    downY = params.y
                    touchX = event.rawX
                    touchY = event.rawY
                    true
                }
                MotionEvent.ACTION_MOVE -> {
                    params.x = downX + (event.rawX - touchX).toInt()
                    params.y = downY + (event.rawY - touchY).toInt()
                    clampPosition()
                    true
                }
                MotionEvent.ACTION_UP, MotionEvent.ACTION_CANCEL -> {
                    val moved = abs(event.rawX - touchX) + abs(event.rawY - touchY)
                    persistPosition()
                    if (event.actionMasked == MotionEvent.ACTION_UP && moved < dp(10)) {
                        detail?.visibility = if (detail?.visibility == View.VISIBLE) View.GONE else View.VISIBLE
                        overlay?.post { clampPosition() }
                    }
                    true
                }
                else -> false
            }
        }
    }

    private fun clampPosition() {
        val params = layout ?: return
        val width = overlay?.measuredWidth?.takeIf { it > 0 } ?: dp(74)
        val height = overlay?.measuredHeight?.takeIf { it > 0 } ?: dp(74)
        params.x = params.x.coerceIn(0, (resources.displayMetrics.widthPixels - width).coerceAtLeast(0))
        params.y = params.y.coerceIn(0, (resources.displayMetrics.heightPixels - height).coerceAtLeast(0))
        try {
            overlay?.let { if (it.isAttachedToWindow) windowManager.updateViewLayout(it, params) }
        } catch (_: Exception) {
            removeOverlay()
        }
    }

    private fun persistPosition() {
        val params = layout ?: return
        getSharedPreferences("zeno_overlay", MODE_PRIVATE).edit().putInt("x", params.x).putInt("y", params.y).apply()
    }

    private fun removeOverlay() {
        try { overlay?.let { if (it.isAttachedToWindow) windowManager.removeViewImmediate(it) } } catch (_: Exception) { }
        overlay = null
        orb = null
        detail = null
    }

    private fun startPolling() {
        if (poller?.isShutdown == false) return
        poller = Executors.newSingleThreadScheduledExecutor { runnable ->
            Thread(runnable, "zeno-android-command-poller").apply { isDaemon = true }
        }.also { service ->
            service.scheduleWithFixedDelay({ pollOnce() }, 0, 5, TimeUnit.SECONDS)
        }
    }

    private fun pollOnce() {
        try {
            ensureOverlayOnMainThread()
            val credentials = SecureStore(this).load() ?: run {
                publishState("PAIR PHONE")
                return
            }
            val client = ApiClient(credentials)
            val now = System.currentTimeMillis()
            if (now - lastHeartbeat >= 15_000) {
                client.heartbeat(if (ZenoAccessibilityService.available()) "overlay active; basic controls enabled" else "overlay active; controls disabled")
                lastHeartbeat = now
            }
            publishState("READY")
            for (command in client.claimCommands()) execute(client, command)
        } catch (error: ApiException) {
            publishState(if (error.status == 401 || error.status == 403) "WAITING APPROVAL" else "OFFLINE")
        } catch (_: Exception) {
            publishState("OFFLINE")
        }
    }

    private fun execute(client: ApiClient, command: ApiClient.RemoteCommand) {
        if (!client.acknowledge(command.id)) return
        publishState("ACTING")
        val result = if (command.rawAction != "android_action") {
            ZenoAccessibilityService.Result(false, "Unsupported command type")
        } else {
            ZenoAccessibilityService.execute(command.operation, command.target)
        }
        try {
            client.complete(command.id, result.ok, result.summary, result.evidence)
            publishState(if (result.ok) "SUCCESS" else "ERROR")
        } catch (_: Exception) {
            publishState("OFFLINE")
        }
    }

    private fun ensureOverlayOnMainThread() {
        overlay?.post { ensureOverlay() } ?: android.os.Handler(mainLooper).post { ensureOverlay() }
    }

    private fun applyState(state: String) {
        val colour = when (state) {
            "ACTING" -> Color.rgb(255, 177, 66)
            "SUCCESS" -> Color.rgb(88, 232, 151)
            "ERROR", "OFFLINE", "OVERLAY ERROR" -> Color.rgb(255, 92, 108)
            "WAITING APPROVAL", "ACCESSIBILITY OFF", "TAP • CONTROLS OFF" -> Color.rgb(185, 151, 255)
            else -> Color.rgb(66, 217, 255)
        }
        orb?.background = orbBackground(colour)
        detail?.findViewWithTag<TextView>(STATE_TEXT_TAG)?.text = "ZENO • $state"
        updateNotification("ZENO: $state")
    }

    companion object {
        private const val CHANNEL_ID = "zeno_overlay_active"
        private const val NOTIFICATION_ID = 321
        private const val STATE_TEXT_TAG = "zeno-state"
        @Volatile private var current: OverlayService? = null

        fun publishState(state: String) {
            current?.let { service ->
                android.os.Handler(service.mainLooper).post {
                    service.applyState(state.take(40))
                }
            }
        }
    }
}
