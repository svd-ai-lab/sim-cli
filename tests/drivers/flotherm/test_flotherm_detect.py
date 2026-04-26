"""Regression tests for FlothermDriver.detect() across .pack and the three
Flotherm XML flavors (FloSCRIPT, FloXML, SmartPart FloXML).

Issue #39: detect() previously matched only FloSCRIPT (`<xml_log_file`),
so `sim lint` mis-routed FloXML authoring files to PyBaMM.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from sim.drivers.flotherm.driver import FlothermDriver


@pytest.fixture
def driver() -> FlothermDriver:
    return FlothermDriver()


class TestDetectXml:
    def test_floscript(self, driver, tmp_path):
        p = tmp_path / "import.xml"
        p.write_text(
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<xml_log_file version="1.0">\n'
            '  <project_import filename="C:/tmp/x.xml" import_type="FloXML"/>\n'
            "</xml_log_file>\n",
            encoding="utf-8",
        )
        assert driver.detect(p) is True

    def test_floxml_xml_case(self, driver, tmp_path):
        p = tmp_path / "model.xml"
        p.write_text(
            '<?xml version="1.0" encoding="UTF-8" standalone="no"?>\n'
            "<xml_case>\n  <name>HBM_demo</name>\n</xml_case>\n",
            encoding="utf-8",
        )
        assert driver.detect(p) is True

    def test_smartpart_floxml(self, driver, tmp_path):
        p = tmp_path / "smartpart.xml"
        p.write_text(
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<sm_xml_case>\n  <name>part</name>\n</sm_xml_case>\n",
            encoding="utf-8",
        )
        assert driver.detect(p) is True

    def test_unrelated_xml_rejected(self, driver, tmp_path):
        p = tmp_path / "other.xml"
        p.write_text(
            '<?xml version="1.0"?>\n<not_flotherm><foo/></not_flotherm>\n',
            encoding="utf-8",
        )
        assert driver.detect(p) is False


class TestDetectPack:
    def test_pack_extension_claimed(self, driver, tmp_path):
        p = tmp_path / "model.pack"
        p.write_bytes(b"")  # contents irrelevant — extension drives detection
        assert driver.detect(p) is True

    def test_other_binary_extension(self, driver, tmp_path):
        p = tmp_path / "model.bin"
        p.write_bytes(b"\x00\x01\x02")
        assert driver.detect(p) is False
