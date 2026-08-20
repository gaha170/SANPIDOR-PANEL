package com.sanpidor.protect

import android.app.admin.DeviceAdminReceiver
import android.content.Context
import android.content.Intent
import android.util.Log

class ProtectDeviceAdmin : DeviceAdminReceiver() {

    override fun onEnabled(context: Context, intent: Intent) {
        Log.d(TAG, "Device admin enabled")
    }

    override fun onDisabled(context: Context, intent: Intent) {
        Log.d(TAG, "Device admin disabled")
    }

    companion object {
        private const val TAG = "ProtectDeviceAdmin"
    }
}
