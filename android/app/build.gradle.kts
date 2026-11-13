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
        versionCode = 3
        versionName = "0.4-rapidocr"
        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
        ndk { abiFilters += listOf("arm64-v8a", "x86_64") }
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    externalNativeBuild {
        cmake { path = file("src/main/cpp/CMakeLists.txt") }
    }
}

chaquopy {
    defaultConfig {
        version = "3.10"
        pip {
            // pyclipper uses the same Clipper 6.4.2 through our native bridge.
            options("--no-deps")
            options("--no-binary", "antlr4-python3-runtime")
            install("numpy==1.26.2")
            install("opencv-python-headless==4.5.1.48")
            install("tomli==2.4.0")
            install("rapidocr==3.10.0")
            install("shapely==1.8.5")
            install("six==1.17.0")
            install("PyYAML==6.0.3")
            install("Pillow==11.0.0")
            install("tqdm==4.67.1")
            install("omegaconf==2.3.0")
            install("antlr4-python3-runtime==4.9.3")
            install("requests==2.32.3")
            install("charset-normalizer==3.4.2")
            install("idna==3.10")
            install("urllib3==2.4.0")
            install("certifi==2025.4.26")
            install("colorlog==6.9.0")
            install("chaquopy-libcxx>=180000")
            install("chaquopy-openblas>=0.2.20")
            install("chaquopy-libgfortran>=4.9")
            install("chaquopy-libpng>=1.6.34")
            install("chaquopy-libjpeg>=1.5.3")
            install("chaquopy-freetype>=2.9.1")
            install("chaquopy-libyaml>=0.2.5")
            install("chaquopy-geos>=3.8.1")
        }
    }
    sourceSets.getByName("main") { srcDir("../../src") }
    sourceSets.getByName("main") { srcDir(layout.buildDirectory.dir("ocr-python")) }
}

val prepareOcr by tasks.registering(Exec::class) {
    workingDir(rootProject.projectDir.parentFile)
    commandLine("uv", "run", "python", "android/prepare_ocr.py",
        layout.buildDirectory.dir("ocr-python/babanongchang_ocr_models").get().asFile.absolutePath)
    inputs.file("../../pyproject.toml")
    inputs.file("../../uv.lock")
    inputs.file("../prepare_ocr.py")
    outputs.dir(layout.buildDirectory.dir("ocr-python"))
}

tasks.configureEach {
    if (name.contains("PythonSources")) dependsOn(prepareOcr)
}

dependencies {
    implementation("com.microsoft.onnxruntime:onnxruntime-android:1.24.3")
    testImplementation("junit:junit:4.13.2")
    androidTestImplementation("androidx.test:runner:1.6.2")
    androidTestImplementation("androidx.test.ext:junit:1.2.1")
}
