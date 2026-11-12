plugins {
    id("com.android.application")
    id("com.chaquo.python")
}

android {
    namespace = "com.babanongchang.android"
    compileSdk = 36

    defaultConfig {
        applicationId = "com.babanongchang.android"
        minSdk = 30
        targetSdk = 36
        versionCode = 2
        versionName = "0.3-cli"
        ndk { abiFilters += listOf("arm64-v8a", "x86_64") }
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
}

chaquopy {
    defaultConfig {
        version = "3.10"
        pip {
            install("numpy==1.26.2")
            install("opencv-python-headless==4.5.1.48")
            install("tomli==2.4.0")
        }
    }
    sourceSets.getByName("main") { srcDir("../../src") }
}

dependencies {
    implementation("com.google.mlkit:text-recognition-chinese:16.0.1")
    testImplementation("junit:junit:4.13.2")
}
