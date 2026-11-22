package com.babanongchang.android

import ai.onnxruntime.OnnxTensor
import ai.onnxruntime.OrtEnvironment
import ai.onnxruntime.OrtSession
import org.json.JSONObject
import java.nio.ByteBuffer
import java.nio.ByteOrder

/** Tensor transport only: RapidOCR retains preprocessing, decoding and filtering. */
class OnnxSession(path: String) : AutoCloseable {
    private val environment = OrtEnvironment.getEnvironment()
    private val session = OrtSession.SessionOptions().use { options ->
        options.setCPUArenaAllocator(false)
        options.setOptimizationLevel(OrtSession.SessionOptions.OptLevel.ALL_OPT)
        environment.createSession(path, options)
    }

    fun inputName(): String = session.inputNames.single()
    fun outputName(): String = session.outputNames.first()
    fun metadata(): String = JSONObject(session.metadata.customMetadata).toString()
    fun customMetadata(key: String): String? = session.metadata.customMetadata[key]

    fun runFloats(values: FloatArray, shape: LongArray): Pair<FloatArray, LongArray> {
        val bytes = ByteBuffer.allocate(values.size * 4).order(ByteOrder.LITTLE_ENDIAN)
        bytes.asFloatBuffer().put(values)
        val output = run(bytes.array(), shape)
        val floats = ByteBuffer.wrap(output.data).order(ByteOrder.LITTLE_ENDIAN).asFloatBuffer()
        return FloatArray(floats.remaining()).also { floats.get(it) } to output.shape
    }

    class Output(val data: ByteArray, val shape: LongArray)

    fun run(data: ByteArray, shape: LongArray): Output {
        val buffer = ByteBuffer.allocateDirect(data.size).order(ByteOrder.LITTLE_ENDIAN)
        buffer.put(data).rewind()
        OnnxTensor.createTensor(environment, buffer.asFloatBuffer(), shape).use { input ->
            session.run(mapOf(inputName() to input)).use { result ->
                val tensor = result[0] as OnnxTensor
                val values = tensor.floatBuffer
                val bytes = ByteBuffer.allocate(values.remaining() * 4).order(ByteOrder.LITTLE_ENDIAN)
                bytes.asFloatBuffer().put(values)
                return Output(bytes.array(), tensor.info.shape)
            }
        }
    }

    override fun close() = session.close()
}
