import unittest
from unittest.mock import patch
from devinspector.core import command_info, detect_languages
from devinspector.reporting import write_report
import tempfile, pathlib

class DetectionTests(unittest.TestCase):
    @patch('devinspector.core.shutil.which', return_value=None)
    def test_missing_command(self, _): self.assertEqual(command_info('absent')['status'],'missing')
    @patch('devinspector.core.shutil.which', side_effect=lambda x: '/usr/bin/python3' if x=='python3' else None)
    @patch('devinspector.core.run')
    def test_language_only_when_detected(self, run, _):
        run.return_value=type('R',(),{'available':True,'stdout':'Python 3.12','stderr':'','returncode':0,'error':None})()
        self.assertEqual(list(detect_languages()),['Python'])
    def test_report_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as d:
            p=pathlib.Path(d)/'out.json'; p.write_text('existing')
            with self.assertRaises(FileExistsError): write_report({'a':1},str(p))
if __name__=='__main__': unittest.main()
