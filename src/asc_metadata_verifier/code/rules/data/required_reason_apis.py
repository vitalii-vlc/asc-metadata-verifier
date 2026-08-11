"""Curated map of required-reason API symbol -> Apple privacy-manifest API
category. NON-EXHAUSTIVE by design (Apple's list evolves); documented as such.
Extend deliberately, with a source link in the commit message."""

REQUIRED_REASON_APIS: dict[str, str] = {
    "UserDefaults": "NSPrivacyAccessedAPICategoryUserDefaults",
    "NSUserDefaults": "NSPrivacyAccessedAPICategoryUserDefaults",
    "systemUptime": "NSPrivacyAccessedAPICategorySystemBootTime",
    "mach_absolute_time": "NSPrivacyAccessedAPICategorySystemBootTime",
    "contentModificationDate": "NSPrivacyAccessedAPICategoryFileTimestamp",
    "creationDate": "NSPrivacyAccessedAPICategoryFileTimestamp",
    "stat": "NSPrivacyAccessedAPICategoryDiskSpace",
    "statfs": "NSPrivacyAccessedAPICategoryDiskSpace",
    "activeInputModes": "NSPrivacyAccessedAPICategoryActiveKeyboards",
}
