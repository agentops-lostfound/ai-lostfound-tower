import unittest,tempfile
from pathlib import Path
from unittest.mock import patch
import numpy as np
from PIL import Image
from .gripper_aperture import save,choose,ticks
from .gap_observation import GapObserver
from .partial_boundary import topview_clearance
from .view_clearance import needs_view,view_heights

class AperturePartialTests(unittest.TestCase):
 def test_minimum_measured_opening_no_interpolation(self):
  profile={'revision':'test','height_mm':5,'margin_mm':6,'gripper_limits':[1345,2800],'rows':[{'percent':40,'width_mm':30},{'percent':70,'width_mm':80}]}
  # v0.2.25: wide objects (>=60mm) open 80%; the largest measured width is the lower bound.
  selected=choose(72,5,profile);self.assertEqual(selected['percent'],80);self.assertEqual(selected['width_mm'],80)
  self.assertEqual(choose(50,5,profile)['percent'],70)
  self.assertEqual(ticks(70,1345,2800),2364)
  with self.assertRaisesRegex(ValueError,'부족'):choose(79,5,profile)
 def test_unmeasured_large_block_small_explicit_exception(self):
  with self.assertRaisesRegex(ValueError,'미측정'):choose(60,5,{'rows':[]})
  self.assertFalse(choose(47,5,{'rows':[]})['verified'])
 def test_wrong_contact_height_does_not_reuse_measurement(self):
  with self.assertRaisesRegex(ValueError,'미측정'):
   choose(70,10,{'height_mm':5,'rows':[{'percent':100,'width_mm':100}]})
 def test_persist_and_reject_nonmonotonic_widths(self):
  with tempfile.TemporaryDirectory() as d:
   path=Path(d)/'widths.json'
   data=save({'rows':[{'percent':50,'width_mm':60},{'percent':80,'width_mm':90}]},path)
   self.assertEqual(choose(73,5,data)['percent'],80)
   with self.assertRaisesRegex(ValueError,'작아'):
    save({'rows':[{'percent':50,'width_mm':90},{'percent':80,'width_mm':60}]},path)
 def observer(self):
  shape={'method':'matched_target_features','box_pixels':[[200,100],[300,100],[300,450],[200,450]],'width_pixels':100,'length_pixels':350}
  finger={'frame_size':[640,480],'contour':[[80,300],[120,300],[120,479],[80,479]]}
  return shape,finger
 def test_low_inliers_reacquires_without_unbound_scale(self):
  shape,finger=self.observer();points=np.float32([[[210+i*5,150+i*10]] for i in range(10)])
  im=Image.new('RGB',(640,480),'green')
  with patch('beta.gap_observation.pink_tube',return_value=shape),patch('cv2.goodFeaturesToTrack',return_value=points):
   o=GapObserver(im,{},finger)
   with patch('cv2.calcOpticalFlowPyrLK',return_value=(points,np.ones((10,1),np.uint8),None)),patch('cv2.estimateAffinePartial2D',return_value=(np.eye(2,3),np.zeros((10,1),np.uint8))):
    result=o.measure(im)
   self.assertEqual(result['registration']['method'],'fresh_target_match')
 def test_out_of_range_scale_reacquires(self):
  shape,finger=self.observer();points=np.float32([[[210+i*5,150+i*10]] for i in range(10)])
  im=Image.new('RGB',(640,480),'green')
  with patch('beta.gap_observation.pink_tube',return_value=shape),patch('cv2.goodFeaturesToTrack',return_value=points):
   o=GapObserver(im,{},finger)
   with patch('cv2.calcOpticalFlowPyrLK',return_value=(points,np.ones((10,1),np.uint8),None)),patch('cv2.estimateAffinePartial2D',return_value=(np.array([[2.,0,0],[0,2.,0]]),np.ones((10,1),np.uint8))):
    result=o.measure(im)
   self.assertEqual(result['registration']['method'],'fresh_target_match')
 def test_direct_pixels_find_neighbor_without_detector(self):
  from PIL import ImageDraw
  image=Image.new('RGB',(400,400),'#609e80');d=ImageDraw.Draw(image);d.rectangle((150,80,250,320),fill='blue');d.rectangle((255,100,278,300),fill='red')
  result=topview_clearance(image,[[150,80],[250,80],[250,320],[150,320]],[100,0],50,10)
  self.assertFalse(result['clear'])
 def test_small_objects_never_get_mandatory_view_lift(self):
  self.assertFalse(needs_view(30,5,640,None,False)['needed'])
  self.assertTrue(needs_view(75,5,640,None,False)['needed'])
  self.assertFalse(needs_view(75,5,640,250,True)['needed'])
  self.assertEqual(view_heights(45),[65.,80.])
if __name__=='__main__':unittest.main()


class WideApertureTests(unittest.TestCase):
    def test_wide_object_opens_80_with_lower_bound_width(self):
        from .gripper_aperture import choose
        p={'rows':[{'percent':50,'width_mm':82.}],'height_mm':5,'margin_mm':6,'revision':'r','gripper_limits':[1345,2800]}
        a=choose(72.7,5,p);self.assertEqual(a['percent'],80);self.assertEqual(a['width_mm'],82.);self.assertTrue(a['width_is_lower_bound'])
        self.assertEqual(choose(47.5,5,p)['percent'],50)
