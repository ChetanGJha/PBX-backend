import unittest
import xml.etree.ElementTree as ET

class TestXmlCdrConfig(unittest.TestCase):
    def test_xml_cdr_conf_validity(self):
        tree = ET.parse("config/freeswitch/autoload_configs/xml_cdr.conf.xml")
        root = tree.getroot()
        self.assertEqual(root.attrib.get("name"), "xml_cdr.conf")
        params = {p.attrib["name"]: p.attrib["value"] for p in root.findall(".//param")}
        self.assertIn("http://api:8000/freeswitch/cdr", params.get("url", ""))
        self.assertEqual(params.get("encode"), "true")

    def test_modules_conf_contains_mod_xml_cdr(self):
        tree = ET.parse("config/freeswitch/autoload_configs/modules.conf.xml")
        root = tree.getroot()
        loaded = [elem.attrib.get("module") for elem in root.findall(".//load")]
        self.assertIn("mod_xml_cdr", loaded)

if __name__ == "__main__":
    unittest.main()
