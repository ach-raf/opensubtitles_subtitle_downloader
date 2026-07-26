"""TUI widgets. Each widget renders a slice of AppState.

Widgets never import ``library/*`` directly; they read state off the App and
post user intents (download, change-language, etc.) back to the App, which
delegates to the typed application actions.
"""
