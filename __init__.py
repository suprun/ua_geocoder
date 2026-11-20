"""UA Geocoder — MIT licensed QGIS plugin."""


def classFactory(iface):
    from .plugin import UaGeocoderPlugin

    return UaGeocoderPlugin(iface)
