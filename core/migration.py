"""Idempotent migration of profile settings and existing project metadata."""

LEGACY_PREFIX = "visicom_data_api/"
PREFIX = "ua_geocoder/"


def migrate_settings(settings) -> None:
    """Copy references to encrypted credentials without opening the auth database."""
    marker = PREFIX + "legacy_settings_migrated"
    if settings.value(marker, False, type=bool):
        return
    for key in settings.allKeys():
        if key.startswith(LEGACY_PREFIX):
            target = PREFIX + key[len(LEGACY_PREFIX):]
            if not settings.contains(target):
                settings.setValue(target, settings.value(key))
    for old, new in (
        ("gui/locator_filters/prefix_visicom_data_api",
         "gui/locator_filters/prefix_ua_geocoder"),
        ("locator-filters/items/visicom_data_api/",
         "locator-filters/items/ua_geocoder/"),
        ("gui/locator_filters/enabled_visicom_data_api",
         "gui/locator_filters/enabled_ua_geocoder"),
    ):
        for key in settings.allKeys():
            if key == old or (old.endswith("/") and key.startswith(old)):
                target = new + key[len(old):]
                if not settings.contains(target):
                    settings.setValue(target, settings.value(key))
    settings.setValue(marker, True)
    settings.sync()


def custom_property(owner, key: str, default=None):
    """Adopt old layer/group metadata when that object is used by the new plugin."""
    # Map layers and layer-tree nodes expose different names in supported QGIS APIs.
    keys = (
        owner.customPropertyKeys()
        if hasattr(owner, "customPropertyKeys") else owner.customProperties()
    )
    if key not in keys and key.startswith(PREFIX):
        legacy = LEGACY_PREFIX + key[len(PREFIX):]
        if legacy in keys:
            owner.setCustomProperty(key, owner.customProperty(legacy))
            owner.removeCustomProperty(legacy)
    return owner.customProperty(key, default)
