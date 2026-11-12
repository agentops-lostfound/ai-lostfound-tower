"""v0.2.59 registry editing: update, rename/merge, delete reference, delete item."""
import tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from .storage import Store

class RegistryEditTests(unittest.TestCase):
    def setUp(self):
        self.t=tempfile.TemporaryDirectory();self.s=Store(Path(self.t.name)/'db.sqlite')
        with self.s.connect() as db:
            for i,c in [('a','usb'),('b','usb'),('p','phone')]:db.execute('INSERT INTO items VALUES(?,?,?,?,?)',(i,i,c,'',0))
            for r,i,h in [('r1','a','h1'),('r2','a','h2'),('r3','b','h2'),('r4','p','h9')]:
                db.execute('INSERT INTO refs VALUES(?,?,?,?,?,?,?)',(r,i,h,'img','[]','{}','m'))
    def tearDown(self):self.t.cleanup()
    def refs(self,i):
        with self.s.connect() as db:return sorted(r[0] for r in db.execute('SELECT hash FROM refs WHERE item_id=?',(i,)))
    def test_update(self):
        with patch.dict('beta.config.CLASSES',{'usb':'x','phone':'y'},clear=True):self.s.update_item('a','새 이름','메모','usb')
        with self.s.connect() as db:self.assertEqual(tuple(db.execute('SELECT name,notes FROM items WHERE id="a"').fetchone()),('새 이름','메모'))
    def test_merge_dedupes_and_removes_source(self):
        r=self.s.merge_item('a','b');self.assertEqual((r['moved'],r['duplicates_removed']),(1,1))
        self.assertEqual(self.refs('b'),['h1','h2']);self.assertEqual(self.refs('a'),[])
    def test_rename(self):
        self.s.merge_item('a','sandisk_usb');self.assertEqual(self.refs('sandisk_usb'),['h1','h2'])
    def test_merge_other_category_refused(self):
        with self.assertRaisesRegex(ValueError,'품목이 다른'):self.s.merge_item('a','p')
    def test_deletes(self):
        self.assertEqual(self.s.delete_reference('r1')['remaining'],1)
        self.assertEqual(self.s.delete_item('a')['references_deleted'],1);self.assertEqual(self.refs('a'),[])

if __name__=='__main__':unittest.main()


class NameSearchTests(unittest.TestCase):
    """v0.2.67: a word only in an item's ID/name/notes (brand) must move it up the text search."""
    def test_brand_word_in_id_beats_closer_photo(self):
        from .config import MODEL_IDS
        from .matching import name_terms
        with tempfile.TemporaryDirectory() as t:
            s=Store(Path(t)/'db.sqlite')
            with s.connect() as db:
                for i,n,note,v in [('sandisk_black_usb','sandisk black usb','',[1,0]),('axxen_usb','gray usb','',[.97,.243]),('u3','usb','민수의 usb',[.96,.28])]:
                    db.execute('INSERT INTO items VALUES(?,?,?,?,?)',(i,n,'usb',note,0))
                    db.execute('INSERT INTO refs VALUES(?,?,?,?,?,?,?)',('r'+i,i,'h'+i,'img',str(v),'{}',MODEL_IDS['sig']))
            q=[1,0]                                        # real gap was ~0.03 (0.157 vs 0.126)
            self.assertEqual(s.rank(q)['candidates'][0]['id'],'sandisk_black_usb')
            terms=name_terms('axxen 검은색 usb',['usb','USB','USB flash drive'])
            self.assertEqual(terms,['axxen'])
            top=s.rank(q,terms=terms)['candidates'][0];self.assertEqual((top['id'],top['name_match']),('axxen_usb',['axxen']))
            self.assertEqual(s.rank(q,terms=name_terms('민수 usb'))['candidates'][0]['id'],'u3')
            self.assertEqual(name_terms('검은색 usb'),[])   # colors/category words stay with the photo+color path


class QueryCategoryTests(unittest.TestCase):
    """v0.2.73: a query naming one category searches only that category."""
    def test_category_words(self):
        from .matching import query_category
        self.assertEqual(query_category('하늘색 핸드폰'),'phone')
        self.assertEqual(query_category('axxen 검은색 usb'),'usb')
        self.assertEqual(query_category('검정 보조배터리'),'power_bank')
        self.assertIsNone(query_category('파란색 물건'))
        self.assertIsNone(query_category('핸드폰이랑 usb'))
