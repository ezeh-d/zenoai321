package com.zeno.companion

import org.json.JSONArray
import org.json.JSONObject
import java.io.BufferedInputStream
import java.net.HttpURLConnection
import java.net.URI
import java.net.URL

class ApiException(val status: Int, message: String) : Exception(message)

class ApiClient(private val credentials: SecureStore.Credentials) {
    data class RemoteCommand(
        val id: String,
        val operation: String,
        val target: String,
        val rawAction: String
    )

    companion object {
        fun normaliseGateway(value: String): String {
            val uri = URI(value.trim())
            require(uri.scheme.equals("https", ignoreCase = true)) { "ZENO gateway must use HTTPS" }
            require(!uri.host.isNullOrBlank() && uri.userInfo == null) { "Invalid ZENO gateway" }
            require(uri.rawQuery == null && uri.rawFragment == null) { "Gateway must not contain a query or fragment" }
            val path = uri.path.orEmpty().trimEnd('/')
            require(path.isEmpty()) { "Gateway must be an origin, without an extra path" }
            return URI("https", null, uri.host, uri.port, null, null, null).toString().trimEnd('/')
        }

        fun claim(gateway: String, credential: String, label: String): SecureStore.Credentials {
            val base = normaliseGateway(gateway)
            val payload = JSONObject()
                .put("credential", credential.trim())
                .put("label", label.trim().take(80))
                .put("protocol_version", "1.0.0")
            val response = request(base, "/api/owner/android/pairing/claim", payload)
            return SecureStore.Credentials(
                base,
                response.getString("device_id"),
                response.getString("token")
            )
        }

        private fun request(base: String, path: String, payload: JSONObject): JSONObject {
            val connection = URL(base + path).openConnection() as HttpURLConnection
            try {
                connection.requestMethod = "POST"
                connection.connectTimeout = 10_000
                connection.readTimeout = 20_000
                connection.doOutput = true
                connection.instanceFollowRedirects = false
                connection.setRequestProperty("Content-Type", "application/json")
                connection.setRequestProperty("Accept", "application/json")
                connection.outputStream.use { it.write(payload.toString().toByteArray(Charsets.UTF_8)) }
                val status = connection.responseCode
                val stream = if (status in 200..299) connection.inputStream else connection.errorStream
                val bytes = BufferedInputStream(stream ?: return JSONObject()).use { input ->
                    val output = java.io.ByteArrayOutputStream()
                    val buffer = ByteArray(4096)
                    while (true) {
                        val count = input.read(buffer)
                        if (count < 0) break
                        if (output.size() + count > 512 * 1024) throw ApiException(status, "Oversized gateway response")
                        output.write(buffer, 0, count)
                    }
                    output.toByteArray()
                }
                val body = JSONObject(bytes.toString(Charsets.UTF_8).ifBlank { "{}" })
                if (status !in 200..299) {
                    val detail = body.optString("detail", "ZENO gateway returned HTTP $status")
                    throw ApiException(status, detail.take(240))
                }
                return body
            } finally {
                connection.disconnect()
            }
        }
    }

    private fun authenticated(extra: JSONObject = JSONObject()): JSONObject = extra
        .put("device_id", credentials.deviceId)
        .put("token", credentials.token)

    fun heartbeat(detail: String): Boolean = request(
        credentials.gateway, "/api/owner/device/heartbeat",
        authenticated(JSONObject().put("state", "ONLINE").put("detail", detail.take(160)))
    ).optBoolean("ok", false)

    fun claimCommands(): List<RemoteCommand> {
        val response = request(
            credentials.gateway, "/api/owner/device/claim",
            authenticated(JSONObject().put("limit", 3))
        )
        val commands = response.optJSONArray("commands") ?: JSONArray()
        return buildList {
            for (index in 0 until commands.length()) {
                val command = commands.getJSONObject(index)
                val payload = command.optJSONObject("payload") ?: JSONObject()
                add(
                    RemoteCommand(
                        id = command.getString("id"),
                        operation = payload.optString("operation", ""),
                        target = payload.optString("target", ""),
                        rawAction = command.optString("action", "")
                    )
                )
            }
        }
    }

    fun acknowledge(commandId: String): Boolean = request(
        credentials.gateway, "/api/owner/device/ack",
        authenticated(JSONObject().put("command_id", commandId))
    ).optBoolean("ok", false)

    fun complete(commandId: String, success: Boolean, summary: String, evidence: JSONObject) {
        val result = JSONObject().put("summary", summary.take(300)).put("evidence", evidence)
        request(
            credentials.gateway, "/api/owner/device/complete",
            authenticated(
                JSONObject().put("command_id", commandId).put("success", success)
                    .put("result", result).put("error", if (success) "" else summary.take(300))
            )
        )
    }
}
