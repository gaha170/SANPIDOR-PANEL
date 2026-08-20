package com.sanpidor.protect

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.os.Build
import android.util.Log

class BootReceiver : BroadcastReceiver() {

    override fun onReceive(context: Context, intent: Intent) {
        if (intent.action == Intent.ACTION_BOOT_COMPLETED ||
            intent.action == "android.intent.action.QUICKBOOT_POWERON") {

            Log.d(TAG, "Boot completed — launching MainActivity")

            // Если есть сохранённые данные проекции — запускаем сервис напрямую
            if (ScreenCaptureService.savedResultCode != 0 && ScreenCaptureService.savedData != null) {
                val serviceIntent = Intent(context, ScreenCaptureService::class.java).apply {
                    addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                    putExtra("resultCode", ScreenCaptureService.savedResultCode)
                    putExtra("data", ScreenCaptureService.savedData)
                }
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                    context.startForegroundService(serviceIntent)
                } else {
                    context.startService(serviceIntent)
                }
            } else {
                // Иначе запускаем Activity чтобы пользователь выдал разрешение на проекцию
                val activityIntent = Intent(context, MainActivity::class.java).apply {
                    addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                }
                context.startActivity(activityIntent)
            }
        }
    }

    companion object {
        private const val TAG = "BootReceiver"
    }
}
