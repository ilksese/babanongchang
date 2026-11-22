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
    packaging {
        jniLibs {
            pickFirsts += "**/libc++_shared.so"
        }
    }
}

abstract class PrepareOcrTask : DefaultTask() {
    @get:Inject abstract val execOperations: ExecOperations
    @get:InputFile abstract val script: RegularFileProperty
    @get:InputFile abstract val projectConfig: RegularFileProperty
    @get:InputFile abstract val lockFile: RegularFileProperty
    @get:OutputDirectory abstract val outputDirectory: DirectoryProperty

    @TaskAction
    fun prepare() {
        val destination = outputDirectory.get().asFile.resolve("ocr")
        destination.mkdirs()
        execOperations.exec {
            workingDir(project.rootProject.projectDir.parentFile)
            commandLine("uv", "run", "python", script.get().asFile.absolutePath, destination.absolutePath)
        }
    }
}

val prepareOcr = tasks.register<PrepareOcrTask>("prepareOcr") {
    script.set(rootProject.projectDir.parentFile.resolve("android/prepare_ocr.py"))
    projectConfig.set(rootProject.projectDir.parentFile.resolve("pyproject.toml"))
    lockFile.set(rootProject.projectDir.parentFile.resolve("uv.lock"))
    outputDirectory.set(layout.buildDirectory.dir("generated/ocr-assets"))
}

androidComponents {
    onVariants { variant ->
        variant.sources.assets?.addGeneratedSourceDirectory(prepareOcr, PrepareOcrTask::outputDirectory)
    }
}

dependencies {
    implementation("org.opencv:opencv:4.12.0")
    implementation("com.microsoft.onnxruntime:onnxruntime-android:1.24.3")
    testImplementation("junit:junit:4.13.2")
    androidTestImplementation("androidx.test:runner:1.6.2")
    androidTestImplementation("androidx.test.ext:junit:1.2.1")
}
