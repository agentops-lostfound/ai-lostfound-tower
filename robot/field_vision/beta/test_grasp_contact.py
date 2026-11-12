import unittest
from PIL import Image,ImageDraw
from .grasp_contact import contact_candidate,verify_lift


class ContactTests(unittest.TestCase):
    def image(self,touch=False):
        image=Image.new('RGB',(640,480),'#609e80');draw=ImageDraw.Draw(image)
        draw.rectangle((250,40,390,410),fill='#e5a1bc')
        draw.rectangle((20,250,249 if touch else 210,479),fill='#ddd8d5')
        draw.rectangle((391 if touch else 430,250,620,479),fill='#ddd8d5')
        return image

    def test_gap_and_bilateral_silhouette(self):
        self.assertFalse(contact_candidate(self.image())['bilateral_contact_candidate'])
        self.assertTrue(contact_candidate(self.image(True))['bilateral_contact_candidate'])

    def test_white_product_label_is_not_finger(self):
        image=Image.new('RGB',(640,480),'#609e80');draw=ImageDraw.Draw(image)
        draw.rectangle((250,40,390,410),fill='#e5a1bc');draw.rectangle((275,260,365,300),fill='white')
        self.assertFalse(contact_candidate(image)['bilateral_contact_candidate'])

    def test_stationary_image_cannot_confirm_lift(self):
        result=verify_lift(self.image(True),self.image(True))
        self.assertFalse(result['grasp_success']);self.assertNotEqual(result['status'],'held_candidate')
