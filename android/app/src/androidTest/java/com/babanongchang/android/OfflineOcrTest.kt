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
        val python = CliPython.get(context)
        val models = python.getModule("babanongchang_ocr_models")
        val manifestPath = java.io.File(models["__file__"].toString()).parentFile!!
        val manifest = JSONObject(java.io.File(manifestPath, "manifest.json").readText())
        val expectedManifest = JSONObject(instrumentation.context.assets.open("models.json").bufferedReader().use { it.readText() })
        for (name in listOf("Det", "Cls", "Rec")) {
            val bytes = java.io.File(manifestPath, "$name.onnx").readBytes()
            val hash = java.security.MessageDigest.getInstance("SHA-256").digest(bytes)
                .joinToString("") { "%02x".format(it) }
            assertEquals(expectedManifest.getString(name), hash)
            assertEquals(manifest.getString(name), hash)
        }
        val module = python.getModule("babanongchang.android")
        val png = instrumentation.context.assets.open("ocr.png").use { it.readBytes() }
        val expected = JSONArray(instrumentation.context.assets.open("ocr.json").bufferedReader().use { it.readText() })
        val actual = JSONArray(module.callAttr("recognize_png", png).toString())
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
        val python = CliPython.get(instrumentation.targetContext)
        val bitmap = android.graphics.Bitmap.createBitmap(100, 100, android.graphics.Bitmap.Config.ARGB_8888)
        bitmap.eraseColor(android.graphics.Color.WHITE)
        val png = java.io.ByteArrayOutputStream().use { output ->
            bitmap.compress(android.graphics.Bitmap.CompressFormat.PNG, 100, output)
            output.toByteArray()
        }
        bitmap.recycle()
        assertEquals("[]", python.getModule("babanongchang.android").callAttr("recognize_png", png).toString())
        val fixtures = JSONArray(instrumentation.context.assets.open("polygons.json").bufferedReader().use { it.readText() })
        val clipper = python.getModule("pyclipper")
        for (index in 0 until fixtures.length()) {
            val fixture = fixtures.getJSONObject(index)
            val points = fixture.getJSONArray("points")
            val polygon = Array(points.length()) { point ->
                doubleArrayOf(points.getJSONArray(point).getDouble(0), points.getJSONArray(point).getDouble(1))
            }
            val offset = clipper.callAttr("PyclipperOffset")
            offset.callAttr("AddPath", polygon, 1, 0)
            val expanded = offset.callAttr("Execute", fixture.getDouble("distance"))
            assertEquals(fixture.getJSONArray("expanded").toString(),
                JSONArray(python.getModule("json").callAttr("dumps", expanded).toString()).toString())
        }
    }
}
