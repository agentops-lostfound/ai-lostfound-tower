import unittest
import numpy as np
from .board_correction import fit,corrected,needed_delta


def point(name,board,right,up,sent=None):
    p={'target_id':name,'board_mm':board,'user_required_move_topview_mm':{'right':right,'up':up}}
    if sent:p['board_target_mm']=sent
    return p


class BoardCorrectionTests(unittest.TestCase):
    def test_up_is_negative_board_y(self):
        self.assertEqual(needed_delta(point('a',[0,0],5,10)).tolist(),[5,-10])

    def test_already_corrected_target_is_included(self):
        # Sent 7mm up already and still needed 3mm more -> total 10mm up.
        self.assertEqual(needed_delta(point('a',[100,100],0,3,sent=[100,93])).tolist(),[0,-10])

    def test_recovers_scale_and_shift(self):
        boards=[[90,60],[310,100],[410,50],[410,150],[90,150]];c=np.mean(boards,0)
        pts=[]
        for b in boards:
            d=.05*(np.asarray(b)-c)+[-2,-8]
            pts.append(point(str(b),b,d[0],-d[1]))
        profile=fit(pts)
        self.assertAlmostEqual(profile['scale'],.05,places=6)
        self.assertAlmostEqual(profile['shift_mm'][1],-8,places=6)
        target,info=corrected([410,50],dict(profile,enabled=True))
        self.assertTrue(np.allclose(np.asarray(target)-[410,50],.05*(np.asarray([410,50])-c)+[-2,-8]))

    def test_disabled_or_missing_profile_is_identity(self):
        self.assertEqual(corrected([1,2],{'enabled':False,'scale':1,'rotation':0,'shift_mm':[9,9],'center_mm':[0,0]})[0],[1.,2.])

    def test_shift_is_capped(self):
        target,_=corrected([0,0],{'scale':0,'rotation':0,'shift_mm':[100,0],'center_mm':[0,0]})
        self.assertAlmostEqual(target[0],25.)


if __name__=='__main__':unittest.main()
