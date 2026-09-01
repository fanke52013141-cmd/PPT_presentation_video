"""Test MCP digital-human resource registration and read dispatch.

Verifies that:
1. Digital-human URI patterns are registered and parsed correctly
2. Resource templates include the 3 new DH entries with proper fields
3. read_resource() dispatches to the right client methods for each DH type
4. Edge cases (disabled config, dict vs list slides, missing slide) are handled
"""

from __future__ import annotations

import json
import pytest
from unittest.mock import MagicMock

from mcp_server.resources import (
    parse_resource_uri,
    list_resource_templates,
    read_resource,
)


# ---------------------------------------------------------------------------
# URI Parsing
# ---------------------------------------------------------------------------

class TestDigitalHumanURIParsing:
    """Verify URI patterns match and extract the right parameters."""

    def test_parse_dh_config(self):
        result = parse_resource_uri("ppt://projects/abc123/digital-human/config")
        assert result is not None
        project_id, rtype, params = result
        assert project_id == "abc123"
        assert rtype == "dh_config"
        assert params["project_id"] == "abc123"

    def test_parse_dh_videos(self):
        result = parse_resource_uri("ppt://projects/proj1/digital-human/videos")
        assert result is not None
        project_id, rtype, params = result
        assert project_id == "proj1"
        assert rtype == "dh_videos"
        assert "slide_id" not in params

    def test_parse_dh_video_slide(self):
        result = parse_resource_uri(
            "ppt://projects/proj1/digital-human/videos/slide_003"
        )
        assert result is not None
        project_id, rtype, params = result
        assert project_id == "proj1"
        assert rtype == "dh_video_slide"
        assert params["slide_id"] == "slide_003"

    def test_parse_dh_config_does_not_match_videos(self):
        """Config pattern must not greedily match the videos path."""
        result = parse_resource_uri(
            "ppt://projects/p1/digital-human/videos/slide_1"
        )
        assert result is not None
        assert result[1] == "dh_video_slide"

    def test_parse_unknown_dh_uri(self):
        result = parse_resource_uri(
            "ppt://projects/p1/digital-human/unknown"
        )
        assert result is None

    def test_parse_dh_video_slide_with_complex_id(self):
        result = parse_resource_uri(
            "ppt://projects/my-proj-2/digital-human/videos/slide_001"
        )
        assert result is not None
        assert result[0] == "my-proj-2"
        assert result[2]["slide_id"] == "slide_001"


# ---------------------------------------------------------------------------
# Resource Templates
# ---------------------------------------------------------------------------

class TestDigitalHumanResourceTemplates:
    """Verify resource template discovery includes DH entries."""

    def test_templates_include_dh_config(self):
        templates = list_resource_templates()
        dh_configs = [
            t for t in templates
            if t["uriTemplate"].endswith("/digital-human/config")
        ]
        assert len(dh_configs) == 1
        t = dh_configs[0]
        assert t["name"] == "Digital Human Config"
        assert t["mimeType"] == "application/json"
        assert "description" in t

    def test_templates_include_dh_videos(self):
        templates = list_resource_templates()
        dh_videos = [
            t for t in templates
            if t["uriTemplate"].endswith("/digital-human/videos")
        ]
        assert len(dh_videos) == 1
        t = dh_videos[0]
        assert t["name"] == "Digital Human Videos"
        assert t["mimeType"] == "application/json"

    def test_templates_include_dh_video_slide(self):
        templates = list_resource_templates()
        dh_slide = [
            t for t in templates
            if "{slide_id}" in t["uriTemplate"]
            and "digital-human" in t["uriTemplate"]
        ]
        assert len(dh_slide) == 1
        t = dh_slide[0]
        assert t["name"] == "Digital Human Slide Video"
        assert t["mimeType"] == "video/mp4"

    def test_total_template_count_increased(self):
        templates = list_resource_templates()
        # 7 original + 3 DH = 10
        assert len(templates) >= 10

    def test_all_dh_templates_use_ppt_scheme(self):
        templates = list_resource_templates()
        dh_templates = [
            t for t in templates if "digital-human" in t["uriTemplate"]
        ]
        for t in dh_templates:
            assert t["uriTemplate"].startswith("ppt://")


# ---------------------------------------------------------------------------
# read_resource Dispatch
# ---------------------------------------------------------------------------

class TestReadDigitalHumanConfig:
    """Verify read_resource() for dh_config type."""

    def test_returns_config_json(self):
        client = MagicMock()
        client.get_digital_human_config.return_value = {
            "enabled": True,
            "presenter": "female_01",
        }
        result = read_resource(
            "ppt://projects/p1/digital-human/config", client
        )
        assert len(result["contents"]) == 1
        content = result["contents"][0]
        assert content["mimeType"] == "application/json"
        parsed = json.loads(content["text"])
        assert parsed["enabled"] is True
        assert parsed["presenter"] == "female_01"
        client.get_digital_human_config.assert_called_once_with("p1")

    def test_returns_unconfigured_when_no_config(self):
        client = MagicMock()
        client.get_digital_human_config.return_value = {
            "enabled": False, "configured": False
        }
        result = read_resource(
            "ppt://projects/p2/digital-human/config", client
        )
        parsed = json.loads(result["contents"][0]["text"])
        assert parsed["enabled"] is False


class TestReadDigitalHumanVideos:
    """Verify read_resource() for dh_videos type."""

    def test_returns_service_and_config(self):
        client = MagicMock()
        client.check_digital_human_health.return_value = {
            "available": True, "health": {"status": "ok"}
        }
        client.get_digital_human_config.return_value = {
            "enabled": True,
            "slides": ["slide_001", "slide_002"],
        }
        result = read_resource(
            "ppt://projects/p1/digital-human/videos", client
        )
        content = result["contents"][0]
        parsed = json.loads(content["text"])
        assert parsed["service"]["available"] is True
        assert parsed["config"]["enabled"] is True
        assert "videos" in parsed

    def test_includes_slide_video_uris(self):
        client = MagicMock()
        client.check_digital_human_health.return_value = {"available": True}
        client.get_digital_human_config.return_value = {
            "enabled": True,
            "slides": ["s1", "s2"],
        }
        result = read_resource(
            "ppt://projects/p1/digital-human/videos", client
        )
        parsed = json.loads(result["contents"][0]["text"])
        assert "s1" in parsed["videos"]
        assert "s2" in parsed["videos"]
        assert parsed["videos"]["s1"]["uri"] == (
            "ppt://projects/p1/digital-human/videos/s1"
        )

    def test_empty_videos_when_disabled(self):
        client = MagicMock()
        client.check_digital_human_health.return_value = {"available": False}
        client.get_digital_human_config.return_value = {
            "enabled": False, "configured": False
        }
        result = read_resource(
            "ppt://projects/p1/digital-human/videos", client
        )
        parsed = json.loads(result["contents"][0]["text"])
        assert parsed["videos"] == {}
        assert parsed["service"]["available"] is False

    def test_empty_videos_when_no_slides_key(self):
        client = MagicMock()
        client.check_digital_human_health.return_value = {"available": True}
        client.get_digital_human_config.return_value = {
            "enabled": True,
        }
        result = read_resource(
            "ppt://projects/p1/digital-human/videos", client
        )
        parsed = json.loads(result["contents"][0]["text"])
        assert parsed["videos"] == {}


class TestReadDigitalHumanVideoSlide:
    """Verify read_resource() for dh_video_slide type."""

    def test_returns_slide_metadata_with_dict_slides(self):
        client = MagicMock()
        client.get_digital_human_config.return_value = {
            "enabled": True,
            "slides": {
                "slide_001": {"presenter": "male_01", "resolution": "1080p"},
                "slide_002": {"presenter": "female_01"},
            },
        }
        result = read_resource(
            "ppt://projects/proj1/digital-human/videos/slide_001", client
        )
        parsed = json.loads(result["contents"][0]["text"])
        assert parsed["slide_id"] == "slide_001"
        assert parsed["configured"] is True
        assert parsed["config"]["presenter"] == "male_01"
        assert "download_url" in parsed
        assert "slide_001" in parsed["download_url"]

    def test_returns_configured_true_with_list_slides(self):
        client = MagicMock()
        client.get_digital_human_config.return_value = {
            "enabled": True,
            "slides": ["slide_001", "slide_002"],
        }
        result = read_resource(
            "ppt://projects/p1/digital-human/videos/slide_001", client
        )
        parsed = json.loads(result["contents"][0]["text"])
        assert parsed["configured"] is True

    def test_returns_configured_false_for_missing_slide(self):
        client = MagicMock()
        client.get_digital_human_config.return_value = {
            "enabled": True,
            "slides": {"slide_001": {"presenter": "male_01"}},
        }
        result = read_resource(
            "ppt://projects/p1/digital-human/videos/slide_999", client
        )
        parsed = json.loads(result["contents"][0]["text"])
        assert parsed["configured"] is False
        assert parsed["config"] == {}

    def test_handles_unconfigured_project(self):
        client = MagicMock()
        client.get_digital_human_config.return_value = {
            "enabled": False, "configured": False
        }
        result = read_resource(
            "ppt://projects/p1/digital-human/videos/slide_001", client
        )
        parsed = json.loads(result["contents"][0]["text"])
        assert parsed["configured"] is False

    def test_download_url_contains_project_and_slide(self):
        client = MagicMock()
        client.base_url = "http://test-server:9999"
        client.get_digital_human_config.return_value = {"enabled": False}
        result = read_resource(
            "ppt://projects/myproj/digital-human/videos/slide_005", client
        )
        parsed = json.loads(result["contents"][0]["text"])
        assert "myproj" in parsed["download_url"]
        assert "slide_005" in parsed["download_url"]


# ---------------------------------------------------------------------------
# Edge Cases
# ---------------------------------------------------------------------------

class TestDigitalHumanResourceEdgeCases:
    """Verify edge case handling."""

    def test_unsupported_dh_type_returns_fallback(self):
        """A URI that matches no pattern should return unknown URI message."""
        client = MagicMock()
        result = read_resource(
            "ppt://projects/p1/digital-human/status", client
        )
        assert "Unknown resource URI" in result["contents"][0]["text"]

    def test_dh_config_mime_type_is_json(self):
        client = MagicMock()
        client.get_digital_human_config.return_value = {"enabled": True}
        result = read_resource(
            "ppt://projects/p1/digital-human/config", client
        )
        assert result["contents"][0]["mimeType"] == "application/json"

    def test_dh_videos_mime_type_is_json(self):
        client = MagicMock()
        client.check_digital_human_health.return_value = {"available": True}
        client.get_digital_human_config.return_value = {"enabled": False}
        result = read_resource(
            "ppt://projects/p1/digital-human/videos", client
        )
        assert result["contents"][0]["mimeType"] == "application/json"

    def test_dh_video_slide_mime_type_is_json(self):
        client = MagicMock()
        client.get_digital_human_config.return_value = {"enabled": False}
        result = read_resource(
            "ppt://projects/p1/digital-human/videos/slide_001", client
        )
        assert result["contents"][0]["mimeType"] == "application/json"
