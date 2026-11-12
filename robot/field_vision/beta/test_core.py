import json
import tempfile
import unittest
from pathlib import Path

from .models import clamp_box, iou, detection_queries, duplicate_detection
from .storage import Store, public
from .engine import Engine
from .matching import color_evidence,text_features


class RegistryContracts(unittest.TestCase):
    def setUp(self):
        self.temp_root=Path(__file__).resolve().parents[1]/'work/test-temporary'
        self.temp_root.mkdir(parents=True,exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(dir=self.temp_root)
        assert Path(self.temp.name).resolve().is_relative_to(self.temp_root.resolve())
        self.store=Store(Path(self.temp.name)/'test.sqlite3')
        self.observation={'id':'obs1','created':1,'items':[{'quality':'accepted','category':'wallet','_embedding':[1.,0.],
            '_hash':'original-pixels','crop':'/media/crop.jpg','features':{'colors':'blue'}}]}
        self.store.save_observation(self.observation)

    def tearDown(self):
        assert Path(self.temp.name).resolve().is_relative_to(self.temp_root.resolve())
        self.temp.cleanup()

    def test_retry_does_not_duplicate_reference(self):
        first=self.store.register('obs1',0,'TEST_W01','wallet','')
        second=self.store.register('obs1',0,'TEST_W01','wallet','')
        self.assertTrue(first['added_reference']);self.assertFalse(second['added_reference'])
        self.assertEqual(self.store.items()[0]['reference_count'],1)

    def test_color_conflict_can_reverse_wrong_image_ranking(self):
        self.observation['items'][0]['features']={'body_color':'blue'}
        self.observation['items'][0]['_embedding']=[.9,.43589]
        self.store.save_observation(self.observation);self.store.register('obs1',0,'BLUE','blue','')
        self.observation['id']='pink'
        self.observation['items'][0].update(_hash='pink',_embedding=[1.,0.],features={'body_color':'pink'})
        self.store.save_observation(self.observation);self.store.register('pink',0,'PINK','pink','')
        ranked=self.store.rank([1.,0.],'wallet',features={'body_color':'blue'})
        self.assertEqual(ranked['candidates'][0]['id'],'BLUE')
        self.assertEqual(ranked['candidates'][1]['color_comparison']['status'],'conflict')
        self.assertAlmostEqual(ranked['candidates'][1]['matching_score'],.7)

    def test_identical_pixels_are_not_matching_evidence(self):
        self.store.register('obs1',0,'TEST_W01','wallet','')
        result=self.store.rank([1.,0.],'wallet','original-pixels')
        self.assertEqual(result['candidates'],[])
        self.assertEqual(result['excluded_identical_images'],1)

    def test_identical_looking_physical_items_stay_ambiguous(self):
        self.store.register('obs1',0,'TEST_W01','wallet A','')
        self.store.register('obs1',0,'TEST_W02','wallet B','')
        result=self.store.rank([1.,0.],'wallet','different-pixels')
        self.assertEqual(result['decision'],'ambiguous')
        self.assertEqual(len(result['candidates']),2)
        self.assertAlmostEqual(result['candidates'][0]['similarity'],result['candidates'][1]['similarity'])

    def test_cannot_merge_different_categories(self):
        self.store.register('obs1',0,'TEST_W01','wallet','')
        self.observation['id']='obs2';self.observation['items'][0]['category']='usb'
        self.store.save_observation(self.observation)
        with self.assertRaises(ValueError): self.store.register('obs2',0,'TEST_W01','usb','')

    def test_uncertain_crop_cannot_be_registered(self):
        self.observation['items'][0]['quality']='review';self.store.save_observation(self.observation)
        with self.assertRaises(ValueError): self.store.register('obs1',0,'TEST_W01','wallet','')

    def test_public_payload_does_not_leak_raw_vectors(self):
        result=public(self.observation)
        self.assertNotIn('_embedding',result['items'][0])
        self.assertNotIn('_hash',result['items'][0])

    def test_group_multiple_references_per_item(self):
        self.store.register('obs1',0,'TEST_W01','wallet','')
        self.observation['id']='obs2';self.observation['items'][0]['_hash']='another-photo'
        self.observation['items'][0]['_embedding']=[.9,.1];self.store.save_observation(self.observation)
        self.store.register('obs2',0,'TEST_W01','wallet','')
        result=self.store.rank([1.,0.],'wallet','query')
        self.assertEqual(len(result['candidates']),1)
        self.assertEqual(self.store.items()[0]['reference_count'],2)

class TrackingContracts(unittest.TestCase):
    def test_clear_body_color_conflict_is_penalized(self):
        self.assertEqual(color_evidence({'body_color':'blue'},{'body_color':'pink'})['penalty'],.30)
        self.assertEqual(color_evidence({'body_color':'blue'},{'body_color':'light blue'})['penalty'],0)
        self.assertEqual(color_evidence({'colors':'blue,pink'},{'body_color':'pink'})['status'],'unknown')
        self.assertEqual(text_features('파란 핸드크림')['body_color'],'blue')

    def test_analysis_delay_waits_and_disappearance_resets_timer(self):
        from unittest.mock import patch
        engine=Engine.__new__(Engine)
        engine.tracks={};engine.track_seq=0;engine.settings={'analysis_delay':5}
        items=[{'category':'wallet','bbox':[10,10,100,100],'reasons':[]}]
        with patch('beta.engine.time.time',return_value=100):
            self.assertEqual(engine.update_tracks(items,'top'),[])
        with patch('beta.engine.time.time',return_value=103):
            self.assertEqual(engine.update_tracks(items,'top'),[])
        with patch('beta.engine.time.time',return_value=106):
            self.assertEqual(len(engine.update_tracks(items,'top')),1)
        with patch('beta.engine.time.time',return_value=107):
            engine.update_tracks([],'top')
            self.assertEqual(engine.update_tracks(items,'top'),[])

    def test_nested_wallet_background_box_is_not_a_second_object(self):
        kept=[{'category':'wallet','bbox':[125,158,415,359]}]
        self.assertTrue(duplicate_detection([13,161,540,365],'wallet',kept))
        self.assertFalse(duplicate_detection([450,150,600,350],'wallet',kept))

    def test_wallet_aliases_remain_one_category_and_keep_usb_mapping(self):
        prompts,categories=detection_queries()
        self.assertEqual(categories[prompts.index('a photo of a card holder')],'wallet')
        self.assertEqual(categories[prompts.index('a photo of a credit card holder')],'wallet')
        self.assertEqual(categories[prompts.index('USB flash drive')],'usb')
        self.assertEqual(set(categories),{'phone','wallet','hand_cream','usb','lip_balm','power_bank'})

    def test_stable_track_is_processed_once_until_it_leaves(self):
        engine=Engine.__new__(Engine)
        engine.tracks={};engine.track_seq=0
        items=[{'category':'wallet','bbox':[10,10,100,100],'reasons':[]}]
        self.assertEqual(engine.update_tracks(items,'top'),[])
        ready=engine.update_tracks(items,'top')
        self.assertEqual(len(ready),1)
        ready[0]['processed']=1
        self.assertEqual(engine.update_tracks(items,'top'),[])
        engine.update_tracks([],'top')
        self.assertEqual(engine.update_tracks(items,'top'),[])
        self.assertEqual(len(engine.update_tracks(items,'top')),1)

if __name__=='__main__': unittest.main()
