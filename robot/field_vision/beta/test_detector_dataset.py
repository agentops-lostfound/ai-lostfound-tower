"""v0.2.54 detector dataset: auto boxes on a foam board, synthesis/export to YOLO format."""
import json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np
from PIL import Image
from . import detector_dataset as dd

POLY=np.float32([[20,20],[620,20],[620,340],[20,340]])

def board(objects=()):
    im=np.zeros((360,640,3),np.uint8);im[:]=(120,215,170)        # lit foam (V>=110)
    for x,y,w,h,c in objects:im[y:y+h,x:x+w]=c
    return Image.fromarray(im)

class DatasetTests(unittest.TestCase):
    def test_auto_boxes_find_dark_and_light_objects(self):
        with patch.object(dd,'board_polygon',return_value=POLY):
            boxes,_,_=dd.auto_boxes(board([(100,100,80,25,(25,40,35)),(300,150,40,90,(230,180,190))]))
        self.assertEqual(sorted(b[:2] for b in boxes),[[100,100],[300,150]])

    def test_object_on_board_edge_rejected(self):
        with patch.object(dd,'board_polygon',return_value=POLY):
            with self.assertRaisesRegex(ValueError,'가장자리'):dd.auto_boxes(board([(0,150,60,40,(20,20,20))]))

    def test_build_writes_yolo_labels(self):
        with tempfile.TemporaryDirectory() as t,patch.object(dd,'ROOT',Path(t)),patch.object(dd,'board_polygon',return_value=POLY),patch.object(dd,'_registry',return_value=type('R',(),{'references':lambda self:[]})()):
            raw=Path(t)/'raw'/'s1';raw.mkdir(parents=True)
            board().save(raw/'0000.jpg');(raw/'0000.json').write_text(json.dumps({'class_id':dd.EMPTY,'boxes':[]}))
            board([(100,100,80,25,(25,40,35))]).save(raw/'0001.jpg');(raw/'0001.json').write_text(json.dumps({'class_id':'usb','boxes':[[100,100,80,25]]}))
            cut=Path(t)/'cutouts'/'usb';cut.mkdir(parents=True)
            rgba=np.zeros((25,80,4),np.uint8);rgba[:,:,:3]=(25,40,35);rgba[:,:,3]=255;Image.fromarray(rgba).save(cut/'a.png')
            s=dd.build(['phone','usb'],synthetic=20)
            self.assertEqual(s['real_frames'],2);self.assertGreater(s['synthetic'],10)
            labels=list((Path(t)/'yolo'/'labels').rglob('*.txt'));lines=[l for f in labels for l in f.read_text().splitlines() if l]
            self.assertTrue(lines and all(l.split()[0]=='1' for l in lines))
            self.assertIn('1: usb',(Path(t)/'yolo'/'data.yaml').read_text())

    def test_reference_alpha_removes_foam_and_pale_board(self):
        for bg in [(120,215,170),(200,215,205)]:          # foam, pale board under other light
            rgb=np.zeros((120,60,3),np.uint8);rgb[:]=bg;rgb[20:100,15:45]=(200,40,50)
            a=dd._reference_alpha(rgb)>0
            self.assertTrue(a[30:90,20:40].all());self.assertFalse(a[:10].any() or a[:,:8].any())

    def test_reference_alpha_keeps_crop_filled_by_object(self):
        rng=np.random.default_rng(0)                       # printed tube filling the whole crop
        rgb=np.clip(np.float32([190,205,200])+rng.normal(0,25,(120,60,3)),0,255).astype(np.uint8)
        self.assertGreater((dd._reference_alpha(rgb)>0).mean(),.9)

    def test_overlap_catches_small_box_inside_big(self):
        self.assertGreater(dd._overlap([10,10,20,10],[0,0,300,200]),.9);self.assertLess(dd._iou([10,10,20,10],[0,0,300,200]),.05)

if __name__=='__main__':unittest.main()


class SceneFilterTests(unittest.TestCase):
    def test_weak_block_holding_strong_usb_is_dropped(self):
        from .scene_filter import suppress_supports
        usb={'bbox':[571,218,674,263],'score':.676};block={'bbox':[566,184,682,302],'score':.18};other={'bbox':[100,100,200,200],'score':.2}
        self.assertEqual(suppress_supports([usb,block,other]),[usb,other])

    def test_marker_fallback_masks_missed_marker(self):
        from .markers import exclude_markers
        im=Image.new('RGB',(320,240),(120,215,170))
        masked,boxes=exclude_markers(im,[[10,10,40,40]])
        self.assertEqual(boxes.found,0);self.assertEqual(len(boxes),1)


class AttachedPartTests(unittest.TestCase):
    def test_cap_of_bigger_object_rejected_lone_usb_kept(self):
        from .scene_filter import reject_attached_parts
        im=board([(100,100,200,50,(230,200,210)),(300,105,25,40,(20,20,40)),(450,200,80,25,(25,40,35))])   # tube+cap touching, lone usb
        im=np.asarray(im).copy();im[105:145,295:305]=(20,20,40);im=Image.fromarray(im)                    # bridge cap to tube
        items=[{'detector_prompt':'trained_yolo','bbox':[295,105,325,145],'quality':'accepted'},
               {'detector_prompt':'trained_yolo','bbox':[450,200,530,225],'quality':'accepted'}]
        with patch.object(dd,'board_polygon',return_value=POLY):reject_attached_parts(im,items)
        self.assertEqual([o['quality'] for o in items],['rejected','accepted'])


class TrainedAloneTests(unittest.TestCase):
    def test_alone_only_when_every_enabled_category_was_learned(self):
        from . import models
        with patch.object(models,'CLASSES',{'usb':'u','phone':'p'}):
            with patch.object(models,'trained_classes',return_value=['usb']):self.assertFalse(models.trained_alone())
            with patch.object(models,'trained_classes',return_value=['phone','usb','wallet']):self.assertTrue(models.trained_alone())
            with patch.object(models,'trained_classes',return_value=[]):self.assertFalse(models.trained_alone())
