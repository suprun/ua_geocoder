"""CRS-safe inputs and QGIS geometry for search results."""

import json
from qgis.PyQt.QtCore import QVariant
from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsFeature,
    QgsField,
    QgsFields,
    QgsGeometry,
    QgsJsonUtils,
    QgsPointXY,
    QgsProject,
    QgsWkbTypes,
)
from .models import point


def source_radius_center(source) -> dict:
    """Read exactly one single-part Point, preferring the layer selection."""
    if not source or not source.isValid():
        raise ValueError("Вибраний шар недоступний.")
    if QgsWkbTypes.flatType(source.wkbType()) != QgsWkbTypes.Point:
        raise ValueError("Для центра радіуса потрібен шар Point, не MultiPoint.")
    selected = source.selectedFeatureCount() > 0
    iterator = source.getSelectedFeatures() if selected else source.getFeatures()
    features = []
    try:
        # Read at most two features: only the distinction zero/one/many matters.
        for feature in iterator:
            features.append(feature)
            if len(features) == 2:
                break
    finally:
        iterator.close()
    if not features:
        raise ValueError("Шар порожній. Для центра радіуса потрібна одна точка.")
    if len(features) != 1:
        raise ValueError(
            "Для центра радіуса виділіть рівно одну точку."
            if selected
            else "Шар містить кілька об’єктів. Виділіть рівно одну точку для центра радіуса."
        )
    geometry = features[0].geometry()
    if geometry.isNull() or geometry.isEmpty():
        raise ValueError("Точка центра радіуса має порожню геометрію.")
    if QgsWkbTypes.flatType(geometry.wkbType()) != QgsWkbTypes.Point:
        raise ValueError("Центр радіуса має бути Point, не MultiPoint.")
    if not source.sourceCrs().isValid():
        raise ValueError("Вхідний шар має мати відому систему координат.")
    transform = QgsCoordinateTransform(
        source.sourceCrs(),
        QgsCoordinateReferenceSystem("EPSG:4326"),
        QgsProject.instance().transformContext(),
    )
    coordinate = transform.transform(QgsPointXY(geometry.asPoint()))
    return {
        "source_id": str(features[0].id()),
        "point": list(point([coordinate.x(), coordinate.y()])),
    }


def output_fields():
    fields = QgsFields()
    for name in (
        "source_id",
        "id",
        "label",
        "address",
        "category",
        "status",
        "attribution",
    ):
        fields.append(QgsField(name, QVariant.String))
    for name in ("rank",):
        fields.append(QgsField(name, QVariant.Int))
    return fields


def result_records(operation, result, request, ids=None):
    """Produce geometry plus safe scalar attributes, keeping input references."""
    if operation in ("objects", "features"):
        for rank, item in enumerate(result, 1):
            attrs = {k: item.get(k) for k in ("id", "label", "address", "category")}
            attrs.update(rank=rank, status="OK", attribution=item.get("attribution", "Visicom"))
            yield {
                "geometry": item.get("geometry")
                or {"type": "Point", "coordinates": item["center"]},
                "attributes": attrs,
            }


def make_feature(record, fields, multi=True):
    feature = QgsFeature(fields)
    attrs = record["attributes"]
    feature.setAttributes([attrs.get(field.name()) for field in fields])
    if record.get("geometry"):
        features = QgsJsonUtils.stringToFeatureList(
            json.dumps({"type": "Feature", "geometry": record["geometry"], "properties": {}})
        )
        if not features:
            raise ValueError("Результат містить некоректну геометрію.")
        geom = QgsGeometry(features[0].geometry())
        if geom.isNull() or geom.isEmpty():
            raise ValueError("Результат містить некоректну геометрію.")
        if multi:
            geom.convertToMultiType()
        feature.setGeometry(geom)
    return feature
