# Development and Research Environment

Status: historical research-environment record from the independent Edge
research phase. This document records environment facts only; it is not a
current Runtime setup guide and must not contain credentials, tokens, personal
health data, or unredacted captures.

## Host

- Platform: WSL2 on x86_64
- Kernel: `6.18.33.2-microsoft-standard-WSL2`
- Python: 3.13.15
- uv: 0.12.15
- Docker: 29.9.2; Compose: 5.6.1
- `/dev/kvm`: present as `root:kvm` with mode `0660`; user access and
  `emulator -accel-check` passed after the approved group change and WSL restart

User-level tools are installed under
`~/.local/share/spectres-edge-mi-health/tools`; Android uses
`~/.local/share/android-sdk`. Executables are linked into `~/.local/bin`.

```bash
export ANDROID_HOME="$HOME/.local/share/android-sdk"
export PATH="$HOME/.local/bin:$PATH"
```

## Static analysis

- Eclipse Temurin OpenJDK: 21.0.13 LTS
- JADX/JADX-GUI: 1.5.6; release ZIP SHA-256 verified
- apktool: 3.0.3; release JAR SHA-256 verified
- Private research directory: `research-local/`, Git-ignored inside the repository

- APK source: Xiaomi's official `watch.iot.mi.com` download page (`region=cn`)
- APK filename: `3.59.2_20261023185032_mihealth.apk`
- Package: `com.mi.health`; version: 3.59.2; build/version code: 359002
- Minimum SDK: 26; target SDK: 35
- Native architectures: `arm64-v8a`, `armeabi-v7a`; no x86/x86_64 libraries
- APK size: 150771625 bytes
- APK SHA-256: `112e603b8342cb134402a6dcabdf3ec16fd5171ec65a1d5f7cb7efd83cb0995d`
- Account region: not recorded
- apktool manifest/resource decode: passed; output is under
  `research-local/jadx/3.59.2_20261023185032-resources`
- JADX decompilation: completed with 397 reported decompilation errors; 49779
  Java files were generated and package/source searches succeeded. The output
  remains under the version-specific local research directory

## Android emulator

- Android command-line tools build: 16111833
- Emulator: 37.2.13.0 (build 16740729); platform-tools/adb: 37.0.1
- All AVDs use the Pixel 6 hardware profile and Android 15, API 35
- `mi-health-research`: `default/x86_64`, userdebug; KVM acceleration, headless
  boot, `adb shell`, and `adb root` passed
- Original Mi Fitness APK installation on `mi-health-research`: failed with
  `INSTALL_FAILED_NO_MATCHING_ABIS`, confirming that this AOSP image has no ARM
  translation
- A `default/arm64-v8a` AVD was also tested, but emulator 37.2.13.0 refused to
  boot it on the x86_64 host with `Avd's CPU Architecture 'arm64' is not
  supported by the QEMU2 emulator on x86_64 host. System image must match the
  host architecture.` The unusable AVD and system image were removed after the
  test
- `mi-health-google-apis`: `google_apis/x86_64`, userdebug; runtime ABI list is
  `x86_64,arm64-v8a` and the native bridge is `libndk_translation.so`
- On `mi-health-google-apis`, KVM acceleration, headless boot, `adb shell`, and
  `adb root` passed; the original APK installed successfully and cold-launched
  through `SplashActivity` to `WelcomeActivity`
- The APK was not modified or repackaged. Testing stopped at the region
  selection page without proceeding to account login

The SDK packages were installed with the current Android CLI:

```bash
android --no-metrics --sdk "$ANDROID_HOME" sdk install platform-tools
android --no-metrics --sdk "$ANDROID_HOME" sdk install emulator
android --no-metrics --sdk "$ANDROID_HOME" sdk install system-images\;android-35\;default\;x86_64
android --no-metrics --sdk "$ANDROID_HOME" sdk install system-images\;android-35\;google_apis\;x86_64
avdmanager create avd --name mi-health-research \
  --package 'system-images;android-35;default;x86_64' --device pixel_6
avdmanager create avd --name mi-health-google-apis \
  --package 'system-images;android-35;google_apis;x86_64' --device pixel_6
emulator -avd mi-health-google-apis -no-window -no-audio -no-boot-anim \
  -gpu swiftshader_indirect
```

The Google APIs image is used only for its ARM-to-x86 native translation, not
because Mi Fitness requires Google APIs. The AOSP ARM64 image itself cannot be
used by this emulator on an x86_64 host.

## HTTPS inspection

- mitmproxy/mitmweb: 12.3.1, installed with `uv tool install --python 3.13
  mitmproxy`
- Controlled host HTTP and HTTPS requests through `127.0.0.1:8080`: passed
- Controlled Android HTTP capture on the AOSP x86_64 AVD: passed
- Controlled Android HTTPS/2 capture with a 200 response on the AOSP x86_64 AVD:
  passed
- On the ARM-translation AVD, Chrome reported `ERR_CERT_AUTHORITY_INVALID` even
  after its restarted process could see the injected CA; this browser-specific
  result is not a passing controlled HTTPS test
- Mi Fitness startup HTTPS inspection on the ARM-translation AVD: passed after
  accepting only the required agreement and leaving the optional experience
  program disabled. HTTP/2 requests to `region.hlth.io.mi.com`,
  `sdkconfig.intl.xiaomi.com`, and `tracking.intl.miui.com` returned 200
  responses; no certificate-pinning blocker occurred
- The test stopped at region selection. No Xiaomi account login has been
  performed, and no health data was collected
- The Android proxy was reset to `:0` and mitmweb was stopped after the test

Android 14 and later load the application system trust store from the
Conscrypt APEX. On these Android 15 AVDs, adding the CA only to
`/system/etc/security/cacerts` or bind-mounting only in the `init` namespace is
insufficient. The working approach copies the stable system CA set, adds the
proxy CA, and bind-mounts it over `/apex/com.android.conscrypt/cacerts` in both
the `init` and `zygote64` mount namespaces. New application processes then
inherit the injected store. This is RAM-only and must be repeated after each
AVD boot. It does not require `adb remount`, system-image modification, APK
modification, or certificate-pinning bypasses.

Run these commands after a fresh AVD boot, with the proxy CA already generated
by mitmproxy:

```bash
hash=$(openssl x509 -inform PEM -subject_hash_old \
  -in "$HOME/.mitmproxy/mitmproxy-ca-cert.pem" -noout)
stage=/data/local/tmp/mitm-zygote-ca
adb root
adb shell mkdir -p "$stage"
adb shell cp -a /system/etc/security/cacerts/. "$stage/"
adb push "$HOME/.mitmproxy/mitmproxy-ca-cert.pem" "$stage/$hash.0"
adb shell chmod 755 "$stage"
adb shell chmod 644 "$stage"/*
adb shell chcon -R u:object_r:system_file:s0 "$stage"
for pid in 1 $(adb shell pidof zygote64); do
  adb shell nsenter -t "$pid" -m -- mount --bind \
    "$stage" /apex/com.android.conscrypt/cacerts
  adb shell nsenter -t "$pid" -m -- \
    ls -l "/apex/com.android.conscrypt/cacerts/$hash.0"
done
```

Force-stop and relaunch the target application after injection. Applications
started before injection do not necessarily inherit the mounted CA set. For
the successful controlled browser test on the AOSP x86_64 AVD, the capture was
`GET https://example.com/?zygote-ca-success HTTP/2.0` with a 200 response.

Run the proxy only on the research host and configure the Android guest after
it is listening. Save raw flows only in the Git-ignored research directory:

```bash
mitmweb --listen-host 127.0.0.1 --listen-port 8080 \
  --web-host 127.0.0.1 --web-port 8081 \
  --save-stream-file "$HOME/projects/Spectres-Edge-Mi-Health/research-local/captures/raw/session.mitm"
adb shell settings put global http_proxy 10.0.2.2:8080
```

After every research session, clear the Android proxy and stop mitmproxy:

```bash
adb shell settings put global http_proxy :0
```

The controlled and startup raw captures remain untracked in `research-local/`.
Certificate-pinning bypasses remain out of scope.

## Artifact handling

Store proprietary and sensitive material only in the Git-ignored
`research-local/` directory. Raw captures belong under `captures/raw`;
decompilation belongs in a version-specific directory under `jadx`. Only
self-authored notes and synthetic or redacted fixtures may be committed.
