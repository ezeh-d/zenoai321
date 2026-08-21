package com.zeno.companion

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class ActionPolicyTest {
    @Test fun basicGlobalActionsAreAllowed() {
        for (operation in listOf("BACK", "HOME", "RECENTS", "NOTIFICATIONS", "QUICK_SETTINGS", "SCROLL_UP", "SCROLL_DOWN")) {
            assertTrue(ActionPolicy.validate(operation, "").allowed)
        }
    }

    @Test fun arbitraryTapTypingAndPaymentAreBlocked() {
        for (operation in listOf("TAP", "TYPE", "GESTURE", "PAY", "SEND", "DELETE", "INSTALL")) {
            assertFalse(ActionPolicy.validate(operation, "").allowed)
        }
    }

    @Test fun onlyNormalLaunchablePackageNamesCanBeRequested() {
        assertTrue(ActionPolicy.validate("OPEN_APP", "com.android.chrome").allowed)
        assertFalse(ActionPolicy.validate("OPEN_APP", "com.android.settings").allowed)
        assertFalse(ActionPolicy.validate("OPEN_APP", "../settings").allowed)
    }
}
