package com.zeno.companion

import android.Manifest
import android.app.Activity
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.Color
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.provider.Settings
import android.text.InputType
import android.view.Gravity
import android.view.View
import android.widget.Button
import android.widget.CheckBox
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import java.util.concurrent.Executors

class MainActivity : Activity() {
    private lateinit var gateway: EditText
    private lateinit var code: EditText
    private lateinit var label: EditText
    private lateinit var status: TextView
    private lateinit var permissionState: TextView
    private val executor = Executors.newSingleThreadExecutor()

    private fun dp(value: Int) = (value * resources.displayMetrics.density).toInt()

    private fun text(value: String, size: Float = 15f, colour: Int = Color.rgb(211, 227, 247)) =
        TextView(this).apply {
            text = value
            textSize = size
            setTextColor(colour)
            setPadding(0, dp(6), 0, dp(6))
        }

    private fun button(value: String, action: () -> Unit) = Button(this).apply {
        text = value
        isAllCaps = false
        setOnClickListener { action() }
    }

    private fun input(hintText: String, secret: Boolean = false) = EditText(this).apply {
        hint = hintText
        setHintTextColor(Color.rgb(105, 128, 159))
        setTextColor(Color.WHITE)
        setSingleLine(true)
        inputType = if (secret) InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_PASSWORD
        else InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_URI
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        window.statusBarColor = Color.rgb(5, 8, 22)
        window.navigationBarColor = Color.rgb(5, 8, 22)

        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(22), dp(26), dp(22), dp(28))
            setBackgroundColor(Color.rgb(5, 8, 22))
        }
        root.addView(text("ZENO COMPANION", 25f, Color.rgb(66, 217, 255)))
        root.addView(text("A visible, owner-controlled Android overlay. ZENO cannot bypass phone permissions, secure screens, games that block overlays, or Family Link.", 14f))

        status = text("Not paired", 14f, Color.rgb(255, 190, 90))
        root.addView(status)
        root.addView(text("PAIR THIS PHONE", 13f, Color.rgb(144, 167, 201)))
        gateway = input("HTTPS gateway shown by ZENO")
        code = input("Six-digit code or QR credential", true)
        label = input("Phone name").apply { setText(Build.MANUFACTURER + " " + Build.MODEL) }
        root.addView(gateway)
        root.addView(code)
        root.addView(label)
        root.addView(button("Pair securely") { pair() })

        root.addView(text("ANDROID PERMISSIONS", 13f, Color.rgb(144, 167, 201)))
        permissionState = text("", 14f)
        root.addView(permissionState)
        root.addView(button("Allow display over other apps") {
            startActivity(Intent(Settings.ACTION_MANAGE_OVERLAY_PERMISSION, Uri.parse("package:$packageName")))
        })
        root.addView(button("Enable basic phone controls") {
            startActivity(Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS))
        })
        root.addView(button("Start ZENO orb") { startOrb() })
        root.addView(button("Stop ZENO orb") { stopService(Intent(this, OverlayService::class.java)) })
        root.addView(button("Open ZENO Anywhere") { openZeno() })

        val startOnBoot = CheckBox(this).apply {
            text = "Start the orb after phone restart"
            setTextColor(Color.WHITE)
            isChecked = getSharedPreferences("zeno_overlay", MODE_PRIVATE).getBoolean("start_on_boot", false)
            setOnCheckedChangeListener { _, checked ->
                getSharedPreferences("zeno_overlay", MODE_PRIVATE).edit().putBoolean("start_on_boot", checked).apply()
            }
        }
        root.addView(startOnBoot)
        root.addView(text("The persistent notification is intentional: Android must show when ZENO is active. The Accessibility service performs only Back/Home/Recents, notification or quick-settings shade, scrolling, and opening a normal app. It never types or taps arbitrary controls.", 12f, Color.rgb(144, 167, 201)))

        setContentView(ScrollView(this).apply {
            isFillViewport = true
            addView(
                root,
                android.view.ViewGroup.LayoutParams(
                    android.view.ViewGroup.LayoutParams.MATCH_PARENT,
                    android.view.ViewGroup.LayoutParams.WRAP_CONTENT,
                ),
            )
        })
        handlePairingIntent(intent)
    }

    override fun onNewIntent(newIntent: Intent) {
        super.onNewIntent(newIntent)
        intent = newIntent
        handlePairingIntent(newIntent)
    }

    override fun onResume() {
        super.onResume()
        val paired = SecureStore(this).load() != null
        status.text = if (paired) "Paired. Approve this Android device in ZENO if it is still pending." else "Not paired"
        permissionState.text = "Overlay: ${if (Settings.canDrawOverlays(this)) "allowed" else "not allowed"}  •  Basic controls: ${if (ZenoAccessibilityService.available()) "enabled" else "not enabled"}"
    }

    override fun onDestroy() {
        executor.shutdownNow()
        super.onDestroy()
    }

    private fun handlePairingIntent(intent: Intent?) {
        val data = intent?.data ?: return
        if (data.scheme != "zeno" || data.host != "pair") return
        gateway.setText(data.getQueryParameter("gateway").orEmpty())
        code.setText(data.getQueryParameter("credential").orEmpty())
        status.text = "Pairing QR received. Press Pair securely."
    }

    private fun pair() {
        val gatewayValue = gateway.text.toString()
        val credentialValue = code.text.toString()
        val labelValue = label.text.toString()
        if (credentialValue.isBlank()) {
            status.text = "Enter the temporary pairing code."
            return
        }
        status.text = "Pairing over HTTPS…"
        executor.execute {
            try {
                val credentials = ApiClient.claim(gatewayValue, credentialValue, labelValue)
                SecureStore(this).save(credentials)
                runOnUiThread {
                    code.text.clear()
                    status.text = "Paired securely. Approve this device in ZENO, then start the orb."
                }
            } catch (error: Exception) {
                runOnUiThread { status.text = "Pairing failed: ${error.message.orEmpty().take(180)}" }
            }
        }
    }

    private fun startOrb() {
        if (!Settings.canDrawOverlays(this)) {
            status.text = "Allow Display over other apps first."
            startActivity(Intent(Settings.ACTION_MANAGE_OVERLAY_PERMISSION, Uri.parse("package:$packageName")))
            return
        }
        if (Build.VERSION.SDK_INT >= 33 && checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(arrayOf(Manifest.permission.POST_NOTIFICATIONS), 42)
        }
        startForegroundService(Intent(this, OverlayService::class.java))
        status.text = "ZENO orb started."
    }

    private fun openZeno() {
        val url = SecureStore(this).load()?.gateway ?: gateway.text.toString().trim()
        if (url.isBlank()) {
            status.text = "Pair the phone or enter the HTTPS ZENO gateway first."
            return
        }
        startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(url.trimEnd('/') + "/app")))
    }
}
