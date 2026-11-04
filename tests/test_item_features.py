import json
import unittest
from vision.item_features import validate_response, CATEGORIES


class ItemFeaturesTests(unittest.TestCase):
    def example(self):
        return {"category": "phone", "colors": ["black"], "shape": "rectangle",
                "materials": [], "logos_or_text": [], "sticker_status": "unknown",
                "stickers": [], "distinctive_features": ["dark screen"]}

    def test_general_categories_and_no_wallet_field(self):
        for category in CATEGORIES:
            value = self.example()
            value["category"] = category
            self.assertEqual(validate_response(json.dumps(value))["category"], category)
        value["wallet_type"] = None
        with self.assertRaises(ValueError):
            validate_response(json.dumps(value))

    def test_invalid_values_and_duplicate_keys_rejected(self):
        for key, item in [("category", "cell phone"), ("colors", "black"),
                          ("materials", [42]), ("shape", 5), ("sticker_status", "invalid")]:
            value = self.example()
            value[key] = item
            with self.assertRaises(ValueError):
                validate_response(json.dumps(value))
        with self.assertRaises(ValueError):
            validate_response('{"category":"phone","category":"wallet"}')
        with self.assertRaises(ValueError):
            validate_response('{"shape":NaN}')

    def test_fenced_json_and_visible_sticker(self):
        value = self.example()
        value.update(sticker_status="present", stickers=[{"shape":"square", "position":"bottom-right"}])
        self.assertEqual(validate_response("```json\n"+json.dumps(value)+"\n```"), value)

    def test_sticker_conflicts_discard_only_uncertain_observations(self):
        for status, stickers in [('present', []), ('absent', [{'shape':'square','position':'back'}]),
                                 ('unknown', [{'shape':'square','position':'back'}])]:
            value=self.example()
            value.update(sticker_status=status, stickers=stickers,
                         distinctive_features=['dark screen', 'square sticker on back'])
            warnings=[]
            result=validate_response(json.dumps(value),warnings=warnings)
            self.assertEqual(result['sticker_status'],'unknown')
            self.assertEqual(result['stickers'],[])
            self.assertEqual(result['distinctive_features'],['dark screen'])
            self.assertEqual(result['colors'],['black'])
            self.assertEqual(warnings,['inconsistent_sticker_fields_discarded'])

    def test_malformed_sticker_and_unrelated_error_still_fail(self):
        for changes in [dict(sticker_status='absent',stickers=[{'shape':42,'position':None}]),
                        dict(sticker_status='present',stickers=[],colors='black')]:
            value=self.example() | changes
            with self.assertRaises(ValueError):
                validate_response(json.dumps(value))
