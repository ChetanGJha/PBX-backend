# tests/test_callcenter_config.py
import xml.etree.ElementTree as ET
import os
import unittest

def get_cfg_path(rel_path: str) -> str:
    if os.path.exists(rel_path):
        return rel_path
    etc_path = os.path.join("/etc/freeswitch", rel_path.replace("config/freeswitch/", ""))
    return etc_path

class TestCallcenterConfig(unittest.TestCase):
    def test_modules_conf_loads_callcenter(self):
        tree = ET.parse(get_cfg_path("config/freeswitch/autoload_configs/modules.conf.xml"))
        root = tree.getroot()
        modules = [m.attrib.get("module") for m in root.findall(".//load")]
        self.assertIn("mod_callcenter", modules)

    def test_callcenter_conf_structure(self):
        path = get_cfg_path("config/freeswitch/autoload_configs/callcenter.conf.xml")
        self.assertTrue(os.path.exists(path))
        tree = ET.parse(path)
        root = tree.getroot()
        moh_params = root.findall(".//param[@name='moh-sound']")
        self.assertGreater(len(moh_params), 0)
        self.assertTrue(any("local_stream://moh" in p.attrib.get("value", "") for p in moh_params))

if __name__ == "__main__":
    unittest.main()
