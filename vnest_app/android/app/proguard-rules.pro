# TVM's native runtime calls these Java classes and methods by name (JNI).
-keep class org.apache.tvm.** { *; }
# MLC LLM engine + kotlinx.serialization protocol classes.
-keep class ai.mlc.mlcllm.** { *; }
-keepattributes *Annotation*, InnerClasses
-dontwarn org.apache.tvm.**
