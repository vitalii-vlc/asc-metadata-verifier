"""Curated denylist of well-known private/undocumented API symbols that have
drawn 2.5.1 rejections. NON-EXHAUSTIVE: Apple's private-API set is proprietary
and vast; this is a high-signal subset. False negatives are expected."""

PRIVATE_API_SYMBOLS: frozenset[str] = frozenset({
    "LSApplicationWorkspace",
    "_UIBackdropView",
    "MPMediaLibrary",  # private selectors historically flagged
    "SBSLaunchApplicationWithIdentifier",
    "setStatusBarHidden",
    "_accessibilityHUDGestureManager",
})
