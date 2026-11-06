"""Public profile tool contract tests; no live browser required."""

import json
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from browser_mcp.tools import ALL_TOOLS, TOOL_HANDLERS, dispatch_tool

PROFILE_DESCRIPTION = (
    "List Chrome profiles without starting Chrome, or open and select a profile. "
    "Starts Chrome if needed; otherwise reuses the profile's existing window and last active tab. "
    "All other browser tools target the selected profile. "
    "Does not restart Chrome or create an extra window for an already-open profile."
)
PROFILE_SCHEMA = {
    "type": "object",
    "properties": {
        "action": {
            "type": "string",
            "enum": ["list_profiles", "open"],
            "description": "List profiles without starting Chrome, or open and select a profile.",
        },
        "profile": {
            "type": "string",
            "description": "Chrome profile display name or directory. Required when action is open.",
        },
    },
    "required": ["action"],
}


class ProfileToolContractTests(unittest.TestCase):
    def test_catalog_has_exactly_13_tools_and_handlers(self):
        expected = {
            "browse_page", "authenticate", "browser_launcher", "session_status",
            "tab_list", "tab_new", "tab_switch", "tab_close", "click_element",
            "fill_input", "scroll_page", "evaluate_js", "take_screenshot",
        }
        self.assertEqual(len(ALL_TOOLS), 13)
        self.assertEqual({tool.name for tool in ALL_TOOLS}, expected)
        self.assertEqual(set(TOOL_HANDLERS), expected)

    def test_profile_schema_and_description_are_exact(self):
        tool = next(tool for tool in ALL_TOOLS if tool.name == "browser_launcher")
        self.assertEqual(tool.description, PROFILE_DESCRIPTION)
        self.assertEqual(tool.inputSchema, PROFILE_SCHEMA)
        exported = json.loads((ROOT / "schemas/browser_launcher.json").read_text())
        self.assertEqual(exported, {
            "name": "browser_launcher", "description": PROFILE_DESCRIPTION,
            "parameters": PROFILE_SCHEMA,
        })

    def test_authenticate_no_longer_advertises_profile(self):
        tool = next(tool for tool in ALL_TOOLS if tool.name == "authenticate")
        self.assertEqual(set(tool.inputSchema["properties"]), {"url", "timeout_seconds"})
        self.assertEqual(tool.description, "Surface a visible browser window for interactive Single Sign-On (SSO / MFA / PingFederate). Automatically saves session state upon successful redirect.")
        exported = json.loads((ROOT / "schemas/authenticate.json").read_text())
        self.assertEqual(set(exported["parameters"]["properties"]), {"url", "timeout_seconds"})
        self.assertNotIn("profile", exported["description"].lower())


class ProfileToolForwardingTests(unittest.IsolatedAsyncioTestCase):
    async def test_profile_dispatch_forwards_arguments_and_result(self):
        for arguments in ({"action": "list_profiles"}, {"action": "open", "profile": "Work"},
                          {"action": "open", "profile": "Profile 1"}, {}):
            with self.subTest(arguments=arguments):
                result = {"success": True, "marker": object()}
                session = SimpleNamespace(browser_launcher=AsyncMock(return_value=result))
                actual = await dispatch_tool(session, "browser_launcher", arguments)
                self.assertIs(actual, result)
                session.browser_launcher.assert_awaited_once_with(
                    action=arguments.get("action"), profile=arguments.get("profile"))

    async def test_old_tool_name_is_not_registered(self):
        with self.assertRaisesRegex(ValueError, "Unknown tool"):
            await dispatch_tool(SimpleNamespace(), "browser_profile", {"action": "list"})

    async def test_authenticate_forwards_original_signature_only(self):
        for arguments, expected in (
            ({}, {"url": None, "timeout_seconds": 900}),
            ({"url": "https://example.com", "timeout_seconds": 15, "profile": "Work"},
             {"url": "https://example.com", "timeout_seconds": 15}),
        ):
            with self.subTest(arguments=arguments):
                result = {"success": True}
                session = SimpleNamespace(authenticate=AsyncMock(return_value=result))
                self.assertIs(await dispatch_tool(session, "authenticate", arguments), result)
                session.authenticate.assert_awaited_once_with(**expected)


if __name__ == "__main__":
    unittest.main()
