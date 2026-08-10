from core.optional_engines import (
    _safe_command_text,
    app_store_source,
    gallery_dl_command,
    parse_package_id,
)

cases = {
    "https://play.google.com/store/apps/details?id=com.example.app": ("google-play", "com.example.app"),
    "https://f-droid.org/packages/org.fdroid.fdroid/": ("f-droid", "org.fdroid.fdroid"),
    "https://apkpure.com/example/com.example.app": ("apk-pure", "com.example.app"),
    "appgallery:com.example.huawei": ("huawei-app-gallery", "com.example.huawei"),
}
for value, expected in cases.items():
    assert (app_store_source(value), parse_package_id(value)) == expected

masked = _safe_command_text(["apkeep", "-e", "person@example.com", "-t", "very-secret", "."])
assert "very-secret" not in masked
assert "********" in masked

command = gallery_dl_command(
    "https://www.instagram.com/p/example/",
    "C:/Downloads",
    browser="firefox",
    browser_profile="default-release",
)
assert "firefox:default-release" in command

print("Optional engines smoke test: OK")
