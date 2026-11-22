package com.babanongchang.android

import androidx.test.platform.app.InstrumentationRegistry
import org.junit.Assert.*
import org.junit.Test
import org.json.JSONArray
import org.json.JSONObject
import android.content.pm.PackageManager

/** No accessibility authorization, target apps or network access are needed. */
class OfflineOcrTest {
    @Test
    fun testPackagedOcrMatchesDesktopFixture() {
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        val context = instrumentation.targetContext
        assertEquals(PackageManager.PERMISSION_DENIED,
            context.checkSelfPermission("android.permission.INTERNET"))
        val manifest = JSONObject(context.assets.open("ocr/manifest.json").bufferedReader().use { it.readText() })
        val expectedManifest = JSONObject(instrumentation.context.assets.open("models.json").bufferedReader().use { it.readText() })
        for (name in listOf("Det", "Cls", "Rec")) {
            val bytes = context.assets.open("ocr/$name.onnx").use { it.readBytes() }
            val hash = java.security.MessageDigest.getInstance("SHA-256").digest(bytes)
                .joinToString("") { "%02x".format(it) }
            assertEquals(expectedManifest.getString(name), hash)
            assertEquals(manifest.getString(name), hash)
        }
        val png = instrumentation.context.assets.open("ocr.png").use { it.readBytes() }
        val expected = JSONArray(instrumentation.context.assets.open("ocr.json").bufferedReader().use { it.readText() })
        val actual = JSONArray(NativeRuntime.recognizeJson(context, png))
        assertTrue("Fixture must contain recognized text", expected.length() > 0)
        assertEquals(expected.length(), actual.length())
        for (index in 0 until expected.length()) {
            val wanted = expected.getJSONArray(index)
            val found = actual.getJSONArray(index)
            assertEquals(wanted.getString(0), found.getString(0))
            assertEquals(wanted.getDouble(2), found.getDouble(2), 0.02)
            for (point in 0..3) for (axis in 0..1) {
                assertEquals(wanted.getJSONArray(1).getJSONArray(point).getDouble(axis),
                    found.getJSONArray(1).getJSONArray(point).getDouble(axis), 2.0)
            }
        }
    }

    @Test
    fun testBlankImageAndNativePolygonExpansion() {
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        val bitmap = android.graphics.Bitmap.createBitmap(100, 100, android.graphics.Bitmap.Config.ARGB_8888)
        bitmap.eraseColor(android.graphics.Color.WHITE)
        val png = java.io.ByteArrayOutputStream().use { output ->
            bitmap.compress(android.graphics.Bitmap.CompressFormat.PNG, 100, output)
            output.toByteArray()
        }
        bitmap.recycle()
        assertEquals("[]", NativeRuntime.recognizeJson(instrumentation.targetContext, png))
        val fixtures = JSONArray(instrumentation.context.assets.open("polygons.json").bufferedReader().use { it.readText() })
        for (index in 0 until fixtures.length()) {
            val fixture = fixtures.getJSONObject(index)
            val points = fixture.getJSONArray("points")
            val polygon = Array(points.length()) { point ->
                doubleArrayOf(points.getJSONArray(point).getDouble(0), points.getJSONArray(point).getDouble(1))
            }
            val expanded = ClipperOffset.execute(polygon.map { it[0] to it[1] }, fixture.getDouble("distance"))
            val actual = org.json.JSONArray()
            expanded.forEach { path ->
                val row = org.json.JSONArray()
                path.forEach { (x, y) -> row.put(org.json.JSONArray().put(x).put(y)) }
                actual.put(row)
            }
            assertEquals(fixture.getJSONArray("expanded").toString(), actual.toString())
        }
    }
}
