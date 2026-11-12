import unittest,tempfile,json
from pathlib import Path
from .category_catalog import Catalog

class CategoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'categories.json'
        self.classes={'usb':'USB flash drive'};self.prompts={'usb':['USB flash drive']};self.names={'usb':'USB'}
        self.catalog=Catalog(self.path,self.classes,self.prompts,self.names)
        self.power=dict(id='power_bank',name='보조배터리',description='portable power bank',prompts=['portable power bank','external battery pack'],enabled=True)
    def test_add_updates_detection_and_classification_and_persists(self):
        self.catalog.change('save',self.power)
        self.assertEqual(self.classes['power_bank'],'portable power bank')
        self.assertIn('external battery pack',self.prompts['power_bank'])
        restored=Catalog(self.path,{}, {},{})
        self.assertEqual(restored.snapshot(),self.catalog.snapshot())
    def test_disable_keeps_display_metadata_but_removes_detection(self):
        self.catalog.change('save',dict(self.power,enabled=False))
        self.assertNotIn('power_bank',self.classes);self.assertNotIn('power_bank',self.prompts)
        self.assertEqual(self.names['power_bank'],'보조배터리')
    def test_delete_does_not_touch_unrelated_files_or_categories(self):
        db=Path(self.tmp.name)/'vision.sqlite3';db.write_bytes(b'existing item data')
        self.catalog.change('save',self.power);self.catalog.change('delete',category_id='power_bank')
        self.assertEqual(db.read_bytes(),b'existing item data');self.assertIn('usb',self.classes)
    def test_invalid_prompt_does_not_modify_saved_config(self):
        self.catalog.change('save',self.power);before=self.path.read_bytes()
        with self.assertRaises(ValueError):self.catalog.change('save',dict(self.power,prompts=['보조배터리']))
        self.assertEqual(self.path.read_bytes(),before)
    def test_delete_all_allowed_for_explicit_no_detection_mode(self):
        self.catalog.change('delete',category_id='usb');self.assertEqual(self.classes,{})
if __name__=='__main__':unittest.main()
