plugins {
    id("com.android.application")
}

android {
    namespace = "com.babanongchang.android"
    compileSdk = 36

    defaultConfig {
        applicationId = "com.babanongchang.android"
        minSdk = 30
        targetSdk = 36
        versionCode = 1
        versionName = "0.2-single-attempt"
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
}

dependencies {
    implementation("com.google.mlkit:text-recognition-chinese:16.0.1")
    testImplementation("junit:junit:4.13.2")
}
