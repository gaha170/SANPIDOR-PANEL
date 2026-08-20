package com.sanpidor.protect

import android.accessibilityservice.AccessibilityService
import android.accessibilityservice.GestureDescription
import android.graphics.Path
import android.util.Log
import android.view.accessibility.AccessibilityEvent

class ProtectAccessibilityService : AccessibilityService() {

    companion object {
        private const val TAG = "ProtectA11y"
        private var instance: ProtectAccessibilityService? = null

        fun performTap(x: Float, y: Float) = instance?.doTap(x, y)
        fun performSwipe(x1: Float, y1: Float, x2: Float, y2: Float, duration: Long) =
            instance?.doSwipe(x1, y1, x2, y2, duration)
        fun performBack()    = instance?.performGlobalAction(GLOBAL_ACTION_BACK)
        fun performHome()    = instance?.performGlobalAction(GLOBAL_ACTION_HOME)
        fun performRecents() = instance?.performGlobalAction(GLOBAL_ACTION_RECENTS)
    }

    override fun onServiceConnected() {
        instance = this
        Log.d(TAG, "Connected")
    }

    // Пустой — не обрабатываем события UI, нет лагов процессора
    override fun onAccessibilityEvent(event: AccessibilityEvent?) = Unit

    override fun onInterrupt() = Unit

    override fun onDestroy() {
        instance = null
        super.onDestroy()
    }

    private fun doTap(x: Float, y: Float) {
        val path = Path().apply { moveTo(x, y) }
        val gesture = GestureDescription.Builder()
            .addStroke(GestureDescription.StrokeDescription(path, 0, 50))
            .build()
        dispatchGesture(gesture, null, null)
    }

    private fun doSwipe(x1: Float, y1: Float, x2: Float, y2: Float, duration: Long) {
        val path = Path().apply { moveTo(x1, y1); lineTo(x2, y2) }
        val gesture = GestureDescription.Builder()
            .addStroke(GestureDescription.StrokeDescription(path, 0, duration))
            .build()
        dispatchGesture(gesture, null, null)
    }
}
