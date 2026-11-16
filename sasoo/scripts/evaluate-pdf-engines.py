#!/usr/bin/env python3
"""Validate stored PDF evaluation evidence without running extractors."""
import argparse
import hashlib
from pathlib import Path
import re
import sys
import json
import math
import unittest



RESOURCE_METRICS = ("wall_time_s", "cpu_time_s", "peak_rss_bytes", "installed_bytes", "cold_load_s", "warm_load_s", "cancel_latency_s", "shutdown_latency_s")


def canonical_hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha256_value(value, label):
    require(isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value), f"{label}: full SHA-256 required")


def finite_number(value, label):
    require(type(value) in (float, int) and math.isfinite(value) and value >= 0, f"{label}: finite nonnegative number required")


def evaluate_pdf(corpus, engines, rubric):
    """Check evidence structure. This function does not measure or approve engines."""
    require(isinstance(corpus, dict) and isinstance(rubric, dict), "corpus and rubric must be objects")
    require(corpus.get("format_version") == 1 and rubric.get("format_version") == 1, "unsupported fixture version")
    documents = corpus.get("documents")
    annotations = corpus.get("annotations", {}).get("items")
    require(isinstance(documents, list) and isinstance(annotations, list) and isinstance(engines, list), "documents, annotations and engines must be lists")
    metrics = rubric.get("metric_names")
    require(isinstance(metrics, list) and metrics and len(set(metrics)) == len(metrics), "unique required metric_names needed")
    require(all(isinstance(name, str) and name for name in metrics), "metric names must be nonempty strings")
    document_map = {}
    for doc in documents:
        require(isinstance(doc, dict) and isinstance(doc.get("id"), str) and doc["id"], "document id required")
        require(doc["id"] not in document_map, "duplicate document id")
        sha256_value(doc.get("source_sha256"), "document source")
        for field in ("origin", "usage_rights", "path"):
            require(isinstance(doc.get(field), str) and doc[field].strip(), f"document {field} required")
        require(isinstance(doc.get("features"), list), "document features required")
        document_map[doc["id"]] = doc
    annotation_map = {}
    for annotation in annotations:
        require(isinstance(annotation, dict), "annotation must be an object")
        doc = document_map.get(annotation.get("document_id"))
        require(doc is not None, "annotation references unknown document")
        require(annotation.get("document_id") not in annotation_map, "duplicate annotation")
        require(annotation.get("source_sha256") == doc["source_sha256"], "annotation source hash mismatch")
        require(annotation.get("ground_truth") == "human_reviewed_original", "ground truth must be human-reviewed original, never baseline output")
        require(all(isinstance(annotation.get(key), str) and annotation[key].strip() for key in ("reviewer", "revision")), "annotation reviewer and revision required")
        require(isinstance(annotation.get("content"), dict) and annotation["content"], "original annotation content required")
        annotation_map[doc["id"]] = annotation
    gaps = []
    if not documents:
        gaps.append("licensed_corpus_absent")
    if set(document_map) != set(annotation_map):
        gaps.append("original_annotations_incomplete")
    features = {feature for doc in documents for feature in doc["features"]}
    if not set(rubric.get("required_features", [])) <= features:
        gaps.append("required_document_features_incomplete")
    frozen = rubric.get("status") == "frozen" and isinstance(rubric.get("frozen_at_utc"), str) and bool(rubric["frozen_at_utc"])
    if not frozen:
        gaps.append("rubric_not_frozen")
    thresholds = rubric.get("thresholds", {})
    require(isinstance(thresholds, dict), "thresholds must be an object")
    for name, value in thresholds.items():
        if value is not None:
            finite_number(value, f"threshold {name}")
    if any(thresholds.get(name) is None for name in metrics):
        gaps.append("acceptance_thresholds_undecided")
    budgets = rubric.get("budgets", {})
    require(isinstance(budgets, dict), "budgets must be an object")
    for name, value in budgets.items():
        if value is not None:
            finite_number(value, f"budget {name}")
    for name in ("wall_time_s", "peak_rss_bytes", "installed_bytes"):
        if budgets.get(name) is None:
            gaps.append("resource_budgets_undecided")
            break
    summaries = []
    engine_ids = set()
    for engine in engines:
        require(isinstance(engine, dict) and isinstance(engine.get("id"), str) and engine["id"], "engine id required")
        require(engine["id"] not in engine_ids, "duplicate engine id")
        engine_ids.add(engine["id"])
        require(isinstance(engine.get("revision"), str) and engine["revision"], "engine revision required")
        sha256_value(engine.get("options_sha256"), "engine options")
        sha256_value(engine.get("model_manifest_sha256"), "engine model manifest")
        records = engine.get("measurements")
        require(isinstance(records, list), "engine measurements must be a list")
        if records:
            require(frozen, "rubric must be frozen before measurements")
            require(not any(gap in gaps for gap in ("acceptance_thresholds_undecided", "resource_budgets_undecided")), "thresholds and budgets must be decided before measurements")
        pairs = set()
        for record in records:
            require(isinstance(record, dict), "measurement must be an object")
            require(record.get("rubric_sha256") == canonical_hash(rubric), "measurement rubric hash mismatch")
            doc_id = record.get("document_id")
            doc = document_map.get(doc_id)
            require(doc is not None, "measurement references unknown document")
            require(record.get("source_sha256") == doc["source_sha256"], "measurement source hash mismatch")
            annotation = annotation_map.get(doc_id)
            require(annotation is not None, "measurement lacks human-reviewed original annotation")
            require(record.get("annotation_sha256") == canonical_hash(annotation), "measurement annotation hash mismatch")
            require(record.get("engine_revision") == engine["revision"], "measurement engine revision mismatch")
            values = record.get("metrics")
            require(isinstance(values, dict) and set(metrics) <= set(values), "missing metrics")
            for name in metrics:
                finite_number(values[name], f"metric {name}")
            for field, status in (("raw_result", None), ("resource_receipt", "verified"), ("target_probe", "passed")):
                receipt = record.get(field)
                require(isinstance(receipt, dict), f"{field} evidence required")
                sha256_value(receipt.get("sha256"), field)
                if status:
                    require(receipt.get("status") == status, f"{field} has no successful receipt")
            require(isinstance(record.get("raw_result", {}).get("path"), str) and record["raw_result"]["path"], "raw_result path required")
            require(record.get("target") in rubric.get("required_targets", []), "measurement target outside declared targets")
            require(isinstance(record.get("hardware"), str) and record["hardware"].strip(), "hardware identity required")
            pair = (doc_id, record["target"])
            require(pair not in pairs, "duplicate document/target measurement")
            pairs.add(pair)
            samples = record.get("samples")
            require(type(record.get("repetitions")) is int and record["repetitions"] > 0 and isinstance(samples, list) and len(samples) == record["repetitions"], "repetitions must match individual samples")
            for sample in samples:
                require(isinstance(sample, dict), "sample must be an object")
                for name in RESOURCE_METRICS:
                    finite_number(sample.get(name), f"sample {name}")
            require(record.get("measured_after_rubric_freeze") is True, "measurement must follow rubric freeze")
            require(isinstance(record.get("instrumentation_overhead"), str) and record["instrumentation_overhead"], "instrumentation overhead required")
        expected_pairs = {(doc_id, target) for doc_id in document_map for target in rubric.get("required_targets", [])}
        if not expected_pairs or pairs != expected_pairs:
            gaps.append(f"target_measurements_incomplete:{engine['id']}")
        summaries.append({"engine_id": engine["id"], "revision": engine["revision"], "stored_record_count": len(records), "evidence_sha256": canonical_hash(records), "metrics_verified": False})
    if not engines:
        gaps.append("engine_measurements_absent")
    gaps.append("independent_review_not_performed")
    # A stored report cannot prove that extraction, measurement or review occurred.
    return {"format_version": 1, "decision": "blocked_pending_measurement", "engine_selection": "legacy", "validation_layer": "stored_evidence_structure", "extraction_ran": False, "quality_verified": False, "source_files_verified": False, "gaps": list(dict.fromkeys(gaps)), "input_hashes": {"corpus_canonical_sha256": canonical_hash(corpus), "rubric_canonical_sha256": canonical_hash(rubric)}, "measurements": summaries}


def load_json(path):
    def reject_constant(value):
        raise ValueError(f"nonfinite JSON constant rejected: {value}")
    value = json.loads(Path(path).read_text(encoding="utf-8"), parse_constant=reject_constant)
    require(isinstance(value, dict), "JSON root must be an object")
    return value


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--corpus", type=Path)
    parser.add_argument("--annotations", type=Path)
    parser.add_argument("--rubric", type=Path)
    parser.add_argument("--measurements", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    if args.self_test:
        result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(EvaluationTests))
        return 0 if result.wasSuccessful() else 1
    if args.corpus is None or args.rubric is None:
        parser.error("--corpus and --rubric are required")
    try:
        corpus = load_json(args.corpus)
        annotation_path = args.annotations or args.corpus.with_name("annotations.json")
        corpus["annotations"] = load_json(annotation_path)
        engines = []
        if args.measurements:
            measurement_input = load_json(args.measurements)
            require("engines" in measurement_input, "measurements file must contain engines")
            engines = measurement_input["engines"]
        report = evaluate_pdf(corpus, engines, load_json(args.rubric))
        report["input_files"] = [{"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()} for path in (args.corpus, annotation_path, args.rubric) + ((args.measurements,) if args.measurements else ())]
        output = json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            with args.output.open("x", encoding="utf-8") as stream:
                stream.write(output)
        print(output, end="")
        return 0
    except (OSError, ValueError, TypeError, KeyError) as error:
        print(json.dumps({"status": "rejected", "error": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 2


class EvaluationTests(unittest.TestCase):
    def empty_inputs(self):
        return ({"format_version": 1, "documents": [], "annotations": {"format_version": 1, "items": []}}, [], {"format_version": 1, "status": "draft", "metric_names": ["character_error_rate"], "required_features": ["digital", "scan"], "required_targets": ["aarch64-apple-darwin", "x86_64-pc-windows-msvc"], "thresholds": {"character_error_rate": None}, "budgets": {"wall_time_s": None, "peak_rss_bytes": None, "installed_bytes": None}})

    def populated_inputs(self):
        corpus, engines, rubric = self.empty_inputs()
        annotation = {"document_id": "synthetic", "source_sha256": "a" * 64, "ground_truth": "human_reviewed_original", "reviewer": "test-reviewer", "revision": "test-v1", "content": {"text": "fixture"}}
        corpus["documents"] = [{"id": "synthetic", "source_sha256": "a" * 64, "origin": "generated test data", "usage_rights": "test-only", "path": "synthetic.pdf", "features": ["digital", "scan"]}]
        corpus["annotations"]["items"] = [annotation]
        rubric.update(status="frozen", frozen_at_utc="2026-11-13T00:00:00Z", thresholds={"character_error_rate": 0.1}, budgets={"wall_time_s": 1.0, "peak_rss_bytes": 100, "installed_bytes": 100})
        record = {"document_id": "synthetic", "source_sha256": "a" * 64, "annotation_sha256": canonical_hash(annotation), "engine_revision": "fixed-test-revision", "metrics": {"character_error_rate": 0.0}, "raw_result": {"sha256": "b" * 64, "path": "raw.json"}, "target": "aarch64-apple-darwin", "hardware": "synthetic test hardware", "repetitions": 1, "samples": [{"wall_time_s": 0.5, "cpu_time_s": 0.25, "peak_rss_bytes": 10, "installed_bytes": 10, "cold_load_s": 0.1, "warm_load_s": 0.01, "cancel_latency_s": 0.1, "shutdown_latency_s": 0.1}], "instrumentation_overhead": "synthetic, not measured", "resource_receipt": {"status": "verified", "sha256": "c" * 64}, "target_probe": {"status": "passed", "sha256": "d" * 64}, "measured_after_rubric_freeze": True}
        record["rubric_sha256"] = canonical_hash(rubric)
        engines.append({"id": "test-engine", "revision": "fixed-test-revision", "options_sha256": "e" * 64, "model_manifest_sha256": "f" * 64, "measurements": [record]})
        return corpus, engines, rubric

    def test_empty_corpus_is_blocked_without_quality_numbers(self):
        report = evaluate_pdf(*self.empty_inputs())
        self.assertEqual(report["decision"], "blocked_pending_measurement")
        self.assertEqual(report["engine_selection"], "legacy")
        self.assertEqual(report["measurements"], [])
        self.assertFalse(report["extraction_ran"])
        self.assertFalse(report["quality_verified"])

    def test_missing_metric_is_rejected(self):
        corpus, engines, rubric = self.populated_inputs()
        engines[0]["measurements"][0]["metrics"] = {}
        with self.assertRaisesRegex(ValueError, "missing metrics"):
            evaluate_pdf(corpus, engines, rubric)

    def test_different_source_is_rejected(self):
        corpus, engines, rubric = self.populated_inputs()
        engines[0]["measurements"][0]["source_sha256"] = "1" * 64
        with self.assertRaisesRegex(ValueError, "source hash mismatch"):
            evaluate_pdf(corpus, engines, rubric)

    def test_baseline_is_not_ground_truth(self):
        corpus, engines, rubric = self.populated_inputs()
        corpus["annotations"]["items"][0]["ground_truth"] = "baseline_engine"
        with self.assertRaisesRegex(ValueError, "human-reviewed original"):
            evaluate_pdf(corpus, engines, rubric)

    def test_nonfinite_measurement_is_rejected(self):
        corpus, engines, rubric = self.populated_inputs()
        engines[0]["measurements"][0]["metrics"]["character_error_rate"] = math.nan
        with self.assertRaisesRegex(ValueError, "finite"):
            evaluate_pdf(corpus, engines, rubric)

    def test_missing_target_resource_evidence_is_rejected(self):
        corpus, engines, rubric = self.populated_inputs()
        del engines[0]["measurements"][0]["target_probe"]
        with self.assertRaisesRegex(ValueError, "target_probe"):
            evaluate_pdf(corpus, engines, rubric)

    def test_unfrozen_rubric_rejects_measurements(self):
        corpus, engines, rubric = self.populated_inputs()
        rubric["status"] = "draft"
        with self.assertRaisesRegex(ValueError, "frozen"):
            evaluate_pdf(corpus, engines, rubric)


    def test_changed_frozen_rubric_is_rejected(self):
        corpus, engines, rubric = self.populated_inputs()
        rubric["thresholds"]["character_error_rate"] = 0.5
        with self.assertRaisesRegex(ValueError, "rubric hash mismatch"):
            evaluate_pdf(corpus, engines, rubric)

    def test_invalid_resource_budget_is_rejected(self):
        corpus, engines, rubric = self.populated_inputs()
        rubric["budgets"]["peak_rss_bytes"] = -1
        with self.assertRaisesRegex(ValueError, "finite nonnegative"):
            evaluate_pdf(corpus, engines, rubric)

    def test_untyped_nested_measurement_is_rejected(self):
        corpus, engines, rubric = self.populated_inputs()
        engines[0]["measurements"] = [None]
        with self.assertRaisesRegex(ValueError, "measurement must be an object"):
            evaluate_pdf(corpus, engines, rubric)

    def test_stored_evidence_does_not_authorize_adoption(self):
        report = evaluate_pdf(*self.populated_inputs())
        self.assertEqual(report["decision"], "blocked_pending_measurement")
        self.assertFalse(report["quality_verified"])
        self.assertIn("independent_review_not_performed", report["gaps"])


if __name__ == "__main__":
    sys.exit(main())
