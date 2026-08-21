package com.zeno.companion

import android.accessibilityservice.AccessibilityService
import android.content.Intent
import android.os.Handler
import android.os.Looper
import android.view.accessibility.AccessibilityEvent
import android.view.accessibility.AccessibilityNodeInfo
import org.json.JSONObject
import java.util.ArrayDeque
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicReference

class ZenoAccessibilityService : AccessibilityService() {
    data class Result(val ok: Boolean, val summary: String, val evidence: JSONObject = JSONObject())

    override fun onServiceConnected() {
        instance = this
        OverlayService.publishState("READY")
    }

    override fun onUnbind(intent: Intent?): Boolean {
        if (instance === this) instance = null
        OverlayService.publishState("ACCESSIBILITY OFF")
        return super.onUnbind(intent)
    }

    override fun onAccessibilityEvent(event: AccessibilityEvent?) = Unit
    override fun onInterrupt() = Unit

    @Suppress("DEPRECATION")
    private fun scroll(action: Int): Boolean {
        val root = rootInActiveWindow ?: return false
        val pending = ArrayDeque<AccessibilityNodeInfo>()
        pending.add(root)
        try {
            var visited = 0
            while (pending.isNotEmpty() && visited < MAX_SCROLL_NODES) {
                val node = pending.removeFirst()
                visited += 1
                try {
                    if (node.isScrollable && node.performAction(action)) return true
                    for (index in 0 until node.childCount) {
                        node.getChild(index)?.let(pending::addLast)
                    }
                } finally {
                    node.recycle()
                }
            }
            return false
        } finally {
            while (pending.isNotEmpty()) pending.removeFirst().recycle()
        }
    }

    private fun executeInternal(operation: String, target: String): Result {
        val decision = ActionPolicy.validate(operation, target)
        if (!decision.allowed) return Result(false, decision.reason)
        val op = operation.trim().uppercase()
        val ok = when (op) {
            "BACK" -> performGlobalAction(GLOBAL_ACTION_BACK)
            "HOME" -> performGlobalAction(GLOBAL_ACTION_HOME)
            "RECENTS" -> performGlobalAction(GLOBAL_ACTION_RECENTS)
            "NOTIFICATIONS" -> performGlobalAction(GLOBAL_ACTION_NOTIFICATIONS)
            "QUICK_SETTINGS" -> performGlobalAction(GLOBAL_ACTION_QUICK_SETTINGS)
            "SCROLL_UP" -> scroll(AccessibilityNodeInfo.ACTION_SCROLL_BACKWARD)
            "SCROLL_DOWN" -> scroll(AccessibilityNodeInfo.ACTION_SCROLL_FORWARD)
            "OPEN_APP" -> {
                val launch = packageManager.getLaunchIntentForPackage(target)
                if (launch == null) false else {
                    launch.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                    startActivity(launch)
                    true
                }
            }
            else -> false
        }
        return Result(
            ok,
            if (ok) "$op was accepted by Android" else "$op was not accepted by Android",
            JSONObject().put("operation", op).put("android_api_accepted", ok)
        )
    }

    companion object {
        private const val MAX_SCROLL_NODES = 256
        @Volatile private var instance: ZenoAccessibilityService? = null

        fun available(): Boolean = instance != null

        fun execute(operation: String, target: String): Result {
            val service = instance ?: return Result(false, "Enable ZENO basic phone controls in Accessibility Settings")
            fun executeSafely() = try {
                service.executeInternal(operation, target)
            } catch (_: Exception) {
                Result(false, "Android rejected the requested basic action")
            }
            if (Looper.myLooper() == service.mainLooper) return executeSafely()
            val result = AtomicReference<Result>()
            val completed = CountDownLatch(1)
            val posted = Handler(service.mainLooper).post {
                try {
                    result.set(executeSafely())
                } finally {
                    completed.countDown()
                }
            }
            if (!posted || !completed.await(4, TimeUnit.SECONDS)) {
                return Result(false, "Android did not process the action in time")
            }
            return result.get() ?: Result(false, "Android returned no action evidence")
        }
    }
}
