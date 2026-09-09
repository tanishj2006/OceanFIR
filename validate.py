#!/usr/bin/env python3

import json
import sys
from datetime import datetime
from pathlib import Path


class Validator:
    def __init__(self, data):
        self.data = data
        self.failed = False

    # ---------------------------------------------------------
    # Basic helpers
    # ---------------------------------------------------------

    def check(self, name, condition):
        if condition:
            print(f"{name:<45} PASS")
        else:
            print(f"{name:<45} FAIL")
            self.failed = True

    @staticmethod
    def is_number(value):
        return isinstance(value, (int, float)) and not isinstance(value, bool)

    @staticmethod
    def is_score(value):
        return (
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and 0.0 <= value <= 1.0
        )

    @staticmethod
    def is_lon_lat(value):
        return (
            isinstance(value, list)
            and len(value) == 2
            and isinstance(value[0], (int, float))
            and isinstance(value[1], (int, float))
            and not isinstance(value[0], bool)
            and not isinstance(value[1], bool)
            and -180.0 <= value[0] <= 180.0
            and -90.0 <= value[1] <= 90.0
        )

    @staticmethod
    def is_iso_datetime(value):
        if not isinstance(value, str):
            return False

        try:
            val_to_parse = value.replace("Z", "+00:00")
            datetime.fromisoformat(val_to_parse)
            return True
        except (ValueError, TypeError):
            return False

    # ---------------------------------------------------------
    # META
    # ---------------------------------------------------------

    def validate_meta(self):
        meta = self.data.get("meta")

        self.check("meta", isinstance(meta, dict))

        if not isinstance(meta, dict):
            return

        self.check("meta.version", meta.get("version") == "2.0")

        self.check(
            "meta.source", meta.get("source") in {"pipeline", "mock"}
        )

        self.check(
            "meta.generated_utc",
            (
                isinstance(meta.get("generated_utc"), str)
                and self.is_iso_datetime(meta.get("generated_utc"))
            ),
        )

        self.check(
            "meta.detector",
            meta.get("detector") in {"classical", "unet-resnet34"},
        )

        self.check(
            "meta.runtime_s",
            (
                self.is_number(meta.get("runtime_s"))
                and meta.get("runtime_s") >= 0
            ),
        )

    # ---------------------------------------------------------
    # SCENE
    # ---------------------------------------------------------

    def validate_scene(self):
        scene = self.data.get("scene")

        self.check("scene", isinstance(scene, dict))

        if not isinstance(scene, dict):
            return

        self.check(
            "scene.id",
            (
                isinstance(scene.get("id"), str)
                and bool(scene.get("id"))
            ),
        )

        self.check(
            "scene.time", isinstance(scene.get("time"), str)
        )

        self.check(
            "scene.time_iso", self.is_iso_datetime(scene.get("time_iso"))
        )

        bbox = scene.get("bbox")

        bbox_valid = (
            isinstance(bbox, list)
            and len(bbox) == 4
            and all(self.is_number(value) for value in bbox)
            and -180 <= bbox[0] <= 180
            and -90 <= bbox[1] <= 90
            and -180 <= bbox[2] <= 180
            and -90 <= bbox[3] <= 90
            and bbox[0] < bbox[2]
            and bbox[1] < bbox[3]
        )

        self.check("scene.bbox", bbox_valid)

        self.check(
            "scene.image", isinstance(scene.get("image"), str)
        )

        self.check("scene.mask", isinstance(scene.get("mask"), str))

        self.check(
            "scene.satellite", isinstance(scene.get("satellite"), str)
        )

        self.check("scene.mode", isinstance(scene.get("mode"), str))

        self.check(
            "scene.polarisation",
            isinstance(scene.get("polarisation"), str),
        )

    # ---------------------------------------------------------
    # DETECTION
    # ---------------------------------------------------------

    def validate_detection(self):
        detection = self.data.get("detection")

        self.check("detection", isinstance(detection, dict))

        if not isinstance(detection, dict):
            return

        self.check(
            "detection.method",
            detection.get("method") in {"classical", "unet-resnet34"},
        )

        self.check(
            "detection.confidence",
            self.is_score(detection.get("confidence")),
        )

        self.check(
            "detection.lookalike_prob",
            self.is_score(detection.get("lookalike_prob")),
        )

        slick = detection.get("slick")

        self.check("detection.slick", isinstance(slick, dict))

        if not isinstance(slick, dict):
            return

        self.check(
            "detection.slick.area_km2",
            (
                self.is_number(slick.get("area_km2"))
                and slick.get("area_km2") >= 0
            ),
        )

        self.check(
            "detection.slick.length_km",
            (
                self.is_number(slick.get("length_km"))
                and slick.get("length_km") >= 0
            ),
        )

        self.check(
            "detection.slick.coverage_pct",
            (
                self.is_number(slick.get("coverage_pct"))
                and 0 <= slick.get("coverage_pct") <= 100
            ),
        )

        polygon = slick.get("polygon")

        polygon_is_list = isinstance(polygon, list)

        polygon_has_valid_count = (
            polygon_is_list and 20 <= len(polygon) <= 60
        )

        polygon_points_valid = polygon_is_list and all(
            self.is_lon_lat(point) for point in polygon
        )

        polygon_is_closed = (
            polygon_is_list
            and len(polygon) >= 2
            and polygon[0] == polygon[-1]
        )

        polygon_valid = (
            polygon_has_valid_count
            and polygon_points_valid
            and polygon_is_closed
        )

        self.check("detection.slick.polygon", polygon_valid)

        self.check(
            "detection.slick.head", self.is_lon_lat(slick.get("head"))
        )

        self.check(
            "detection.slick.centroid",
            self.is_lon_lat(slick.get("centroid")),
        )

        age = slick.get("age_hours_est")

        age_valid = age is None or (
            isinstance(age, list)
            and len(age) == 2
            and all(self.is_number(value) for value in age)
            and age[0] >= 0
            and age[0] <= age[1]
        )

        self.check("detection.slick.age_hours_est", age_valid)

    # ---------------------------------------------------------
    # DRIFT
    # ---------------------------------------------------------

    def validate_drift(self):
        drift = self.data.get("drift")

        if drift is None:
            self.check("drift", True)
            return

        self.check("drift", isinstance(drift, dict))

        if not isinstance(drift, dict):
            return

        self.check(
            "drift.method", isinstance(drift.get("method"), str)
        )

        self.check(
            "drift.origin", self.is_lon_lat(drift.get("origin"))
        )

        self.check(
            "drift.origin_time_iso",
            self.is_iso_datetime(drift.get("origin_time_iso")),
        )

        self.check(
            "drift.uncertainty_km",
            (
                self.is_number(drift.get("uncertainty_km"))
                and drift.get("uncertainty_km") >= 0
            ),
        )

        path = drift.get("path")

        path_valid = isinstance(path, list) and all(
            isinstance(point, list)
            and len(point) == 3
            and self.is_lon_lat(point[:2])
            and self.is_iso_datetime(point[2])
            for point in path
        )

        self.check("drift.path", path_valid)

        if "ensemble" in drift:
            ensemble = drift.get("ensemble")
            self.check("drift.ensemble", isinstance(ensemble, list))

    # ---------------------------------------------------------
    # VESSELS
    # ---------------------------------------------------------

    def validate_vessels(self):
        vessels = self.data.get("vessels")

        self.check("vessels", isinstance(vessels, list))

        if not isinstance(vessels, list):
            return

        valid_verdicts = {"accused", "suspect", "cleared"}

        score_fields = [
            "score",
            "proximity",
            "parity",
            "temporality",
            "silence",
        ]

        for index, vessel in enumerate(vessels):
            prefix = f"vessels[{index}]"

            self.check(f"{prefix}", isinstance(vessel, dict))

            if not isinstance(vessel, dict):
                continue

            self.check(
                f"{prefix}.mmsi",
                (
                    isinstance(vessel.get("mmsi"), int)
                    and not isinstance(vessel.get("mmsi"), bool)
                ),
            )

            self.check(
                f"{prefix}.name", isinstance(vessel.get("name"), str)
            )

            self.check(
                f"{prefix}.type", isinstance(vessel.get("type"), str)
            )

            self.check(
                f"{prefix}.len_m",
                (
                    self.is_number(vessel.get("len_m"))
                    and vessel.get("len_m") >= 0
                ),
            )

            for score_name in score_fields:
                self.check(
                    f"{prefix}.{score_name}",
                    self.is_score(vessel.get(score_name)),
                )

            self.check(
                f"{prefix}.ais_gap_min",
                (
                    self.is_number(vessel.get("ais_gap_min"))
                    and vessel.get("ais_gap_min") >= 0
                ),
            )

            self.check(
                f"{prefix}.dist_km",
                (
                    self.is_number(vessel.get("dist_km"))
                    and vessel.get("dist_km") >= 0
                ),
            )

            self.check(
                f"{prefix}.dark", isinstance(vessel.get("dark"), bool)
            )

            verdict = vessel.get("verdict")

            self.check(
                f"{prefix}.verdict", verdict in valid_verdicts
            )

            reason = vessel.get("reason")

            if verdict == "cleared":
                reason_valid = isinstance(reason, str) and bool(
                    reason.strip()
                )
            else:
                reason_valid = reason is None

            self.check(f"{prefix}.reason", reason_valid)

            track = vessel.get("track")

            if track is None:
                track_valid = True
            elif isinstance(track, list):
                track_valid = all(
                    point is None or self.is_lon_lat(point)
                    for point in track
                )
            else:
                track_valid = False

            self.check(f"{prefix}.track", track_valid)

        valid_vessel_dicts = [
            vessel
            for vessel in vessels
            if isinstance(vessel, dict)
            and self.is_score(vessel.get("score"))
        ]

        accused_vessels = [
            vessel
            for vessel in vessels
            if isinstance(vessel, dict)
            and vessel.get("verdict") == "accused"
        ]

        if accused_vessels:
            if len(valid_vessel_dicts) >= 2:
                ranked_vessels = sorted(
                    valid_vessel_dicts,
                    key=lambda v: v.get("score"),
                    reverse=True,
                )

                top_vessel = ranked_vessels[0]
                second_vessel = ranked_vessels[1]

                top_score = top_vessel.get("score")
                second_score = second_vessel.get("score")

                margin = top_score - second_score

                accused_invariant_valid = (
                    len(accused_vessels) == 1
                    and accused_vessels[0] is top_vessel
                    and round(margin, 6) >= 0.08
                )

                self.check(
                    "vessels.accused_margin", accused_invariant_valid
                )

            elif len(valid_vessel_dicts) == 1:
                top_vessel = valid_vessel_dicts[0]

                accused_invariant_valid = (
                    len(accused_vessels) == 1
                    and accused_vessels[0] is top_vessel
                )

                self.check(
                    "vessels.accused_margin", accused_invariant_valid
                )

            else:
                self.check("vessels.accused_margin", False)
        else:
            self.check("vessels.accused_margin", True)

    # ---------------------------------------------------------
    # DARK CONTACTS
    # ---------------------------------------------------------

    def validate_dark_contacts(self):
        dark_contacts = self.data.get("dark_contacts")
        self.check("dark_contacts", isinstance(dark_contacts, list))

    # ---------------------------------------------------------
    # SUMMARY
    # ---------------------------------------------------------

    def validate_summary(self):
        summary = self.data.get("summary")

        self.check("summary", isinstance(summary, dict))

        if not isinstance(summary, dict):
            return

        vessels = self.data.get("vessels", [])

        if not isinstance(vessels, list):
            vessels = []

        accused_vessels = [
            v
            for v in vessels
            if isinstance(v, dict) and v.get("verdict") == "accused"
        ]

        suspect_vessels = [
            v
            for v in vessels
            if isinstance(v, dict) and v.get("verdict") == "suspect"
        ]

        cleared_vessels = [
            v
            for v in vessels
            if isinstance(v, dict) and v.get("verdict") == "cleared"
        ]

        accused_count = len(accused_vessels)
        suspect_count = len(suspect_vessels)
        cleared_count = len(cleared_vessels)

        summary_verdict = summary.get("verdict")

        self.check(
            "summary.verdict",
            summary_verdict in {"accused", "no_attribution"},
        )

        accused_mmsi = summary.get("accused_mmsi")

        if summary_verdict == "no_attribution":
            accused_mmsi_valid = accused_mmsi is None
        elif summary_verdict == "accused":
            accused_mmsi_valid = (
                isinstance(accused_mmsi, int)
                and not isinstance(accused_mmsi, bool)
                and any(
                    isinstance(vessel, dict)
                    and vessel.get("mmsi") == accused_mmsi
                    for vessel in vessels
                )
            )
        else:
            accused_mmsi_valid = False

        self.check("summary.accused_mmsi", accused_mmsi_valid)

        self.check(
            "summary.threshold", self.is_score(summary.get("threshold"))
        )

        self.check(
            "summary.n_scored", summary.get("n_scored") == len(vessels)
        )

        self.check(
            "summary.n_suspect",
            summary.get("n_suspect") == suspect_count,
        )

        self.check(
            "summary.n_cleared",
            summary.get("n_cleared") == cleared_count,
        )

        if "n_accused" in summary:
            self.check(
                "summary.n_accused",
                summary.get("n_accused") == accused_count,
            )

        self.check(
            "summary.note", isinstance(summary.get("note"), str)
        )

    # ---------------------------------------------------------
    # FULL VALIDATION
    # ---------------------------------------------------------

    def validate(self):
        print()
        print("OceanFIR v2.0 Validator")
        print("=======================")
        print()

        self.validate_meta()
        print()

        self.validate_scene()
        print()

        self.validate_detection()
        print()

        self.validate_drift()
        print()

        self.validate_vessels()
        print()

        self.validate_dark_contacts()
        print()

        self.validate_summary()
        print()

        print("=======================")

        if self.failed:
            print("RESULT: FAIL")
        else:
            print("RESULT: PASS")

        return not self.failed


# -------------------------------------------------------------
# MAIN
# -------------------------------------------------------------


def main():
    if len(sys.argv) != 2:
        print("Usage: python validate.py <data.json>")
        sys.exit(2)

    json_path = Path(sys.argv[1])

    if not json_path.exists():
        print(f"ERROR: File not found: {json_path}")
        sys.exit(2)

    try:
        with json_path.open("r", encoding="utf-8") as file:
            data = json.load(file)
    except json.JSONDecodeError as error:
        print(f"ERROR: Invalid JSON: {error}")
        sys.exit(2)

    if not isinstance(data, dict):
        print("ERROR: Root JSON value must be an object")
        sys.exit(1)

    validator = Validator(data)
    success = validator.validate()

    if success:
        sys.exit(0)

    sys.exit(1)


if __name__ == "__main__":
    main()