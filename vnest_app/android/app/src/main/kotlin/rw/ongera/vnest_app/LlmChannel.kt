package rw.ongera.vnest_app

import ai.mlc.mlcllm.MLCEngine
import ai.mlc.mlcllm.OpenAIProtocol.ChatCompletionMessage
import ai.mlc.mlcllm.OpenAIProtocol.ChatCompletionRole
import ai.mlc.mlcllm.OpenAIProtocol.ResponseFormat
import ai.mlc.mlcllm.OpenAIProtocol.StreamOptions
import android.content.Context
import android.os.SystemClock
import android.util.Log
import io.flutter.plugin.common.BinaryMessenger
import io.flutter.plugin.common.MethodCall
import io.flutter.plugin.common.MethodChannel
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.launch
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext
import java.io.File

/**
 * Bridge between Dart (lib/services/llm_service.dart) and the on-device MLC LLM engine.
 *
 * Channel "vnest/llm":
 *   status({modelId})                                   -> {modelDir, modelPresent, loaded}
 *   load({modelId, modelLib, engine?})                  -> {ms}   (engine = extra MLC EngineConfig fields)
 *   generateJson({system, user, schema, maxTokens})     -> {text, completionTokens, decodeTps, ms}
 *   unload()                                            -> true
 *
 * Weights live in <external files dir>/<modelId>/ (copied over USB or downloaded once).
 * Everything runs on the phone; no network is used.
 */
class LlmChannel(private val context: Context, messenger: BinaryMessenger) :
    MethodChannel.MethodCallHandler {

    private val channel = MethodChannel(messenger, "vnest/llm")
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private val lock = Mutex() // one generation at a time: the GPU can't usefully run two
    private var engine: MLCEngine? = null
    private var loadedModelId: String? = null

    init {
        channel.setMethodCallHandler(this)
    }

    private fun modelDir(modelId: String) = File(context.getExternalFilesDir(""), modelId)

    override fun onMethodCall(call: MethodCall, result: MethodChannel.Result) {
        when (call.method) {
            "status" -> {
                val id: String = call.argument("modelId")!!
                val dir = modelDir(id)
                result.success(
                    mapOf(
                        "modelDir" to dir.absolutePath,
                        "modelPresent" to File(dir, "mlc-chat-config.json").exists(),
                        "loaded" to (loadedModelId == id),
                    )
                )
            }
            "load" -> run(result) {
                val t = SystemClock.elapsedRealtime()
                val id: String = call.argument("modelId")!!
                val engine: Map<String, Any> = call.argument("engine") ?: emptyMap()
                Log.i("VnestLlm", "load start $id engine=$engine")
                load(id, call.argument("modelLib")!!, engine)
                val ms = SystemClock.elapsedRealtime() - t
                Log.i("VnestLlm", "load done $id in $ms ms")
                mapOf("ms" to ms)
            }
            "generateJson" -> run(result) {
                generateJson(
                    system = call.argument("system")!!,
                    user = call.argument("user")!!,
                    schema = call.argument("schema")!!,
                    maxTokens = call.argument<Int>("maxTokens") ?: 120,
                )
            }
            "unload" -> run(result) {
                engine?.unload()
                loadedModelId = null
                true
            }
            else -> result.notImplemented()
        }
    }

    private fun run(result: MethodChannel.Result, block: suspend () -> Any) {
        scope.launch {
            try {
                val value = lock.withLock { block() }
                withContext(Dispatchers.Main) { result.success(value) }
            } catch (e: Throwable) {
                Log.e("VnestLlm", "LLM call failed", e)
                withContext(Dispatchers.Main) { result.error("LLM_ERROR", e.message ?: e.toString(), null) }
            }
        }
    }

    private fun load(modelId: String, modelLib: String, overrides: Map<String, Any>) {
        if (loadedModelId == modelId) return
        val dir = modelDir(modelId)
        require(File(dir, "mlc-chat-config.json").exists()) { "Model files not found in $dir" }
        val e = engine ?: MLCEngine().also { engine = it }
        e.unload()
        e.reload(dir.absolutePath, modelLib, overrides)
        Thread.sleep(300) // let the engine's background loop start (it fails fast if the GPU is unusable)
        checkEngineAlive()
        loadedModelId = modelId
    }

    /** The engine's background threads record fatal errors instead of crashing the app. */
    private fun checkEngineAlive() {
        val err = ai.mlc.mlcllm.BackgroundWorker.lastBackgroundError ?: return
        engine = null
        loadedModelId = null
        throw IllegalStateException("The on-device model stopped: ${err.message?.lineSequence()?.firstOrNull() ?: err}")
    }

    /**
     * One chat completion with grammar-constrained decoding: MLC only lets the model emit tokens
     * that keep the output valid against `schema`. Content is still checked on the Dart side.
     */
    private suspend fun generateJson(system: String, user: String, schema: String, maxTokens: Int): Map<String, Any?> {
        checkEngineAlive()
        val e = engine ?: error("Model not loaded")
        e.reset() // each request is independent; no chat history
        val t = SystemClock.elapsedRealtime()
        val stream = e.chat.completions.create(
            messages = listOf(
                ChatCompletionMessage(role = ChatCompletionRole.system, content = system),
                ChatCompletionMessage(role = ChatCompletionRole.user, content = user),
            ),
            temperature = 0.3f,
            max_tokens = maxTokens,
            stream_options = StreamOptions(include_usage = true),
            response_format = ResponseFormat(type = "json_object", schema = schema),
        )
        Log.i("VnestLlm", "generate start (prompt ${system.length + user.length} chars, max $maxTokens tokens)")
        val out = StringBuilder()
        var completionTokens: Int? = null
        var decodeTps: Float? = null
        var firstMs: Long? = null
        for (chunk in stream) {
            chunk.usage?.let {
                completionTokens = it.completion_tokens
                decodeTps = it.extra?.decode_tokens_per_s
                Log.i("VnestLlm", "usage prompt=${it.prompt_tokens} completion=${it.completion_tokens} " +
                    "prefill_tps=${it.extra?.prefill_tokens_per_s} decode_tps=${it.extra?.decode_tokens_per_s}")
            }
            if (chunk.choices.isNotEmpty()) {
                val piece = chunk.choices[0].delta.content?.asText().orEmpty()
                if (firstMs == null && piece.isNotEmpty()) {
                    firstMs = SystemClock.elapsedRealtime() - t
                    Log.i("VnestLlm", "first token after $firstMs ms")
                }
                out.append(piece)
            }
        }
        Log.i("VnestLlm", "generate done in ${SystemClock.elapsedRealtime() - t} ms, ${out.length} chars")
        return mapOf(
            "text" to out.toString(),
            "completionTokens" to completionTokens,
            "decodeTps" to decodeTps?.toDouble(),
            "ms" to (SystemClock.elapsedRealtime() - t),
        )
    }
}
