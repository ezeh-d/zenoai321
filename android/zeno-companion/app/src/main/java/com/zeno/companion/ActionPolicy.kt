package com.zeno.companion

/** Pure, testable boundary between a cloud command and Android APIs. */
object ActionPolicy {
    val allowedOperations = setOf(
        "BACK", "HOME", "RECENTS", "NOTIFICATIONS", "QUICK_SETTINGS",
        "SCROLL_UP", "SCROLL_DOWN", "OPEN_APP"
    )

    private val packageName = Regex("^[A-Za-z][A-Za-z0-9_]*(\\.[A-Za-z0-9_]+)+$")
    private val forbiddenPackages = setOf(
        "com.android.settings",
        "com.android.permissioncontroller",
        "com.google.android.permissioncontroller",
        "com.android.packageinstaller",
        "com.google.android.packageinstaller",
        "com.zeno.companion"
    )

    data class Decision(val allowed: Boolean, val reason: String = "")

    fun validate(operation: String, target: String): Decision {
        val op = operation.trim().uppercase()
        val value = target.trim()
        if (op !in allowedOperations) return Decision(false, "Unsupported phone action")
        if (op != "OPEN_APP" && value.isNotEmpty()) {
            return Decision(false, "This phone action does not accept a target")
        }
        if (op == "OPEN_APP") {
            if (!packageName.matches(value)) return Decision(false, "Invalid Android package name")
            if (value.lowercase() in forbiddenPackages) {
                return Decision(false, "Security and permission apps cannot be opened remotely")
            }
        }
        return Decision(true)
    }
}
