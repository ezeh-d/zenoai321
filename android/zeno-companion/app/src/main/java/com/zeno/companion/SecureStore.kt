package com.zeno.companion

import android.content.Context
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import java.security.KeyStore
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

/** Device credentials are encrypted by a non-exportable Android Keystore key. */
class SecureStore(context: Context) {
    private val preferences = context.getSharedPreferences("zeno_secure_device", Context.MODE_PRIVATE)

    data class Credentials(val gateway: String, val deviceId: String, val token: String)

    private fun key(): SecretKey {
        val store = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
        (store.getKey(KEY_ALIAS, null) as? SecretKey)?.let { return it }
        return KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore").run {
            init(
                KeyGenParameterSpec.Builder(
                    KEY_ALIAS,
                    KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT
                ).setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                    .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                    .setKeySize(256)
                    .build()
            )
            generateKey()
        }
    }

    private fun seal(value: String): String {
        val cipher = Cipher.getInstance("AES/GCM/NoPadding")
        cipher.init(Cipher.ENCRYPT_MODE, key())
        return listOf(cipher.iv, cipher.doFinal(value.toByteArray(Charsets.UTF_8)))
            .joinToString(".") { Base64.encodeToString(it, Base64.NO_WRAP or Base64.URL_SAFE) }
    }

    private fun open(value: String): String {
        val pieces = value.split(".")
        require(pieces.size == 2) { "Invalid encrypted preference" }
        val iv = Base64.decode(pieces[0], Base64.NO_WRAP or Base64.URL_SAFE)
        val encrypted = Base64.decode(pieces[1], Base64.NO_WRAP or Base64.URL_SAFE)
        val cipher = Cipher.getInstance("AES/GCM/NoPadding")
        cipher.init(Cipher.DECRYPT_MODE, key(), GCMParameterSpec(128, iv))
        return cipher.doFinal(encrypted).toString(Charsets.UTF_8)
    }

    fun save(credentials: Credentials) {
        preferences.edit()
            .putString(GATEWAY, seal(credentials.gateway))
            .putString(DEVICE, seal(credentials.deviceId))
            .putString(TOKEN, seal(credentials.token))
            .apply()
    }

    fun load(): Credentials? = try {
        val gateway = preferences.getString(GATEWAY, null) ?: return null
        val device = preferences.getString(DEVICE, null) ?: return null
        val token = preferences.getString(TOKEN, null) ?: return null
        Credentials(open(gateway), open(device), open(token))
    } catch (_: Exception) {
        clear()
        null
    }

    fun clear() = preferences.edit().clear().apply()

    companion object {
        private const val KEY_ALIAS = "zeno_companion_device_v1"
        private const val GATEWAY = "gateway"
        private const val DEVICE = "device"
        private const val TOKEN = "token"
    }
}
