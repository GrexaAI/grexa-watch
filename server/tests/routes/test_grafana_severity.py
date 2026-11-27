"""Warning labels must not become Critical merely because the alert is firing."""

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest


@pytest.fixture
def tasks(monkeypatch):
    # Load the real task module without booting Celery, RCA or database services.
    celery = ModuleType("celery_config")

    class App:
        def task(self, *args, **kwargs):
            return lambda fn: fn

    celery.celery_app = App()
    prompt = ModuleType("chat.background.rca_prompt_builder")
    prompt.build_rca_prompt = lambda *a, **k: ("prompt", "rail")
    correlation = ModuleType("services.correlation")
    correlation.apply_correlation_outcome = lambda *a, **k: None
    correlator = ModuleType("services.correlation.alert_correlator")
    correlator.AlertCorrelator = object
    for name, module in (
        ("celery_config", celery), ("chat.background.rca_prompt_builder", prompt),
        ("services.correlation", correlation), ("services.correlation.alert_correlator", correlator),
    ):
        monkeypatch.setitem(sys.modules, name, module)
    path = Path(__file__).parents[2] / "routes" / "grafana" / "tasks.py"
    spec = importlib.util.spec_from_file_location("grafana_severity_under_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("label,expected", [
    ("critical", "critical"), ("high", "high"), ("medium", "medium"), ("low", "low"),
    ("warning", "high"), ("warn", "high"), (" WARNING ", "high"),
    ("info", "low"), ("informational", "low"), (" CRITICAL ", "critical"),
])
def test_explicit_label_takes_priority_over_firing_state(tasks, label, expected):
    assert tasks._extract_severity({"state": "alerting", "commonLabels": {"severity": label}}) == expected


def test_common_labels_do_not_hide_instance_severity(tasks):
    assert tasks._extract_severity({"state": "alerting", "commonLabels": {"environment": "prod"}, "labels": {"severity": "warning"}}) == "high"


def test_grouped_alerts_preserve_each_instance_severity(tasks):
    payload = {"state": "alerting", "commonLabels": {"environment": "prod"}}
    for severity, expected in (("warning", "high"), ("critical", "critical")):
        merged = tasks._merge_alert_into_payload(payload, {"status": "firing", "labels": {"severity": severity}})
        assert tasks._extract_severity(merged) == expected
    assert payload["commonLabels"] == {"environment": "prod"}


@pytest.mark.parametrize("severity", [None, "", "unexpected", 123])
def test_unrecognized_explicit_severity_is_not_promoted_to_critical(tasks, severity):
    assert tasks._extract_severity({"state": "alerting", "labels": {"severity": severity}}) == "unknown"


@pytest.mark.parametrize("state,expected", [("alerting", "critical"), ("pending", "high"), ("ok", "low"), ("no_data", "unknown")])
def test_legacy_payload_without_severity_keeps_state_fallback(tasks, state, expected):
    assert tasks._extract_severity({"state": state}) == expected


def test_resolved_warning_retains_its_explicit_severity(tasks):
    assert tasks._extract_severity({"state": "ok", "labels": {"severity": "warning"}}) == "high"
