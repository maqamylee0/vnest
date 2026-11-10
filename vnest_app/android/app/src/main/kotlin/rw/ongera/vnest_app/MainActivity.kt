package rw.ongera.vnest_app

import io.flutter.embedding.android.FlutterActivity
import io.flutter.embedding.engine.FlutterEngine

class MainActivity : FlutterActivity() {
    override fun configureFlutterEngine(flutterEngine: FlutterEngine) {
        super.configureFlutterEngine(flutterEngine)
        LlmChannel(applicationContext, flutterEngine.dartExecutor.binaryMessenger)
    }
}
