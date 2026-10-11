import java.io.FileInputStream
import java.util.Properties

plugins {
    id("com.android.application")
    // The Flutter Gradle Plugin must be applied after the Android and Kotlin Gradle plugins.
    id("dev.flutter.flutter-gradle-plugin")
}

// Release signing lives in android/key.properties (gitignored) and points at
// app/amr-release.keystore. Absent a key file, release falls back to the debug
// key so a fresh clone still builds a runnable APK.
val keystoreProperties = Properties()
val keystorePropertiesFile = rootProject.file("key.properties")
if (keystorePropertiesFile.exists()) {
    keystorePropertiesFile.inputStream().use { keystoreProperties.load(it) }
}

// Resolve the keystore tolerantly. The project is often copied to a new folder,
// which leaves an absolute `storeFile` in key.properties pointing at the old
// location and breaks the build. Prefer the configured path, then the keystore
// that sits next to this build file.
val configuredStoreFile = keystoreProperties["storeFile"] as String?
val releaseKeystore = configuredStoreFile?.let { file(it) }?.takeIf { it.exists() }
    ?: file("amr-release.keystore").takeIf { it.exists() }
val hasReleaseKeystore = keystorePropertiesFile.exists() && releaseKeystore != null

android {
    namespace = "dev.abhi.robot.amr_controller"
    compileSdk = flutter.compileSdkVersion
    // Allow reusing a locally-installed NDK via AMR_NDK_VERSION instead of
    // downloading Flutter's default (~1.3 GB). Unset on a normal machine, so
    // this is a no-op unless explicitly requested.
    ndkVersion = System.getenv("AMR_NDK_VERSION") ?: flutter.ndkVersion

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    defaultConfig {
        applicationId = "dev.abhi.robot.amr_controller"
        // You can update the following values to match your application needs.
        // For more information, see: https://flutter.dev/to/review-gradle-config.
        minSdk = flutter.minSdkVersion
        targetSdk = flutter.targetSdkVersion
        // Uses the version code from pubspec.yaml. When using split APKs, 1000 * ABI_VERSION
        // is added automatically by Flutter. (https://developer.android.com/studio/build/configure-apk-splits#configure-APK-versions)
        // You can force using the value of versionCode by specifying the `-P force-version-code-ignoring-abi=true`
        // flag during build.
        versionCode = flutter.versionCode
        versionName = flutter.versionName
    }

    signingConfigs {
        create("release") {
            keyAlias = keystoreProperties["keyAlias"] as String?
            keyPassword = keystoreProperties["keyPassword"] as String?
            storeFile = releaseKeystore
            storePassword = keystoreProperties["storePassword"] as String?
        }
    }

    buildTypes {
        release {
            signingConfig = if (hasReleaseKeystore) {
                signingConfigs.getByName("release")
            } else {
                signingConfigs.getByName("debug")
            }
        }
    }
}

kotlin {
    compilerOptions {
        jvmTarget = org.jetbrains.kotlin.gradle.dsl.JvmTarget.JVM_17
    }
}

flutter {
    source = "../.."
}
