import unittest
from xml.etree.ElementTree import Element
from unittest.mock import patch, MagicMock
from src.xml_curl.dialplan import add_voicemail_block

class TestVoicemailDialplan(unittest.TestCase):
    @patch("src.xml_curl.dialplan.ensure_voicemail_prompt", return_value="/var/lib/freeswitch/recordings/prompts/voicemail_1001.wav")
    def test_add_voicemail_block_actions(self, mock_prompt):
        cond = Element("condition")
        add_voicemail_block(cond, "1001", "pbx.local", "tenant-123")
        actions = cond.findall("action")
        apps = [a.attrib.get("application") for a in actions]

        self.assertIn("answer", apps)
        self.assertIn("playback", apps)
        self.assertIn("record", apps)
        self.assertIn("curl", apps)
        self.assertIn("hangup", apps)

        # Verify 1000Hz beep tone playback
        beep_actions = [a for a in actions if a.attrib.get("application") == "playback" and "tone_stream" in a.attrib.get("data", "")]
        self.assertTrue(len(beep_actions) > 0)
        self.assertIn("%(500,0,1000)", beep_actions[0].attrib["data"])

        # Verify record command parameters: 120s limit, 200 threshold, 4s silence terminate
        rec_action = [a for a in actions if a.attrib.get("application") == "record"][0]
        self.assertIn("120 200 4", rec_action.attrib["data"])

    @patch("src.xml_curl.dialplan.os.path.exists", return_value=True)
    def test_add_voicemail_block_with_custom_greeting(self, mock_exists):
        cond = Element("condition")
        custom_wav = "/var/lib/freeswitch/recordings/audio/custom_greeting_1001.wav"
        add_voicemail_block(cond, "1001", "pbx.local", "tenant-123", custom_greeting_path=custom_wav)
        actions = cond.findall("action")
        playback_data = [a.attrib.get("data") for a in actions if a.attrib.get("application") == "playback"]
        self.assertIn(custom_wav, playback_data)

if __name__ == "__main__":
    unittest.main()
