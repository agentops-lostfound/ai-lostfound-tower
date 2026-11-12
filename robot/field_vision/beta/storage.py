import hashlib
from contextlib import contextmanager
import json
import re
import sqlite3
import threading
import time
import uuid
from pathlib import Path

import numpy as np
from .matching import color_evidence, name_match

from .config import CLASSES, MODEL_IDS


def public(value):
    if isinstance(value, dict):
        return {k: public(v) for k, v in value.items() if not k.startswith('_')}
    if isinstance(value, list):
        return [public(v) for v in value]
    return value


class Store:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        with self.connect() as db:
            db.executescript('''
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS observations(id TEXT PRIMARY KEY, created REAL NOT NULL, payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS items(id TEXT PRIMARY KEY, name TEXT NOT NULL, category TEXT NOT NULL, notes TEXT NOT NULL, created REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS refs(id TEXT PRIMARY KEY, item_id TEXT NOT NULL REFERENCES items(id), hash TEXT NOT NULL,
              image TEXT NOT NULL, embedding TEXT NOT NULL, features TEXT NOT NULL, model TEXT NOT NULL,
              UNIQUE(item_id, hash));
            ''')

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        try:
            with db:
                yield db
        finally:
            db.close()

    def save_observation(self, result):
        with self.lock, self.connect() as db:
            db.execute('INSERT OR REPLACE INTO observations VALUES(?,?,?)',
                       (result['id'], result['created'], json.dumps(result, ensure_ascii=False)))

    def observation(self, key):
        with self.connect() as db:
            row = db.execute('SELECT payload FROM observations WHERE id=?', (key,)).fetchone()
        if row is None:
            raise ValueError('분석 기록을 찾을 수 없습니다.')
        return json.loads(row['payload'])

    def observations(self, limit=30):
        with self.connect() as db:
            rows = db.execute('SELECT payload FROM observations ORDER BY created DESC LIMIT ?', (limit,)).fetchall()
        return [public(json.loads(row['payload'])) for row in rows]

    def clear_observations(self):
        # Preserve a recoverable archive and every registry reference/photo.
        with self.lock, self.connect() as db:
            rows=db.execute('SELECT payload FROM observations').fetchall()
            if rows:
                archive=self.path.parent/'archives'
                archive.mkdir(exist_ok=True)
                (archive/('observations-'+uuid.uuid4().hex+'.json')).write_text(
                    '['+','.join(row['payload'] for row in rows)+']',encoding='utf-8')
            db.execute('DELETE FROM observations')
        return len(rows)

    def register(self, observation_id, index, item_id, name, notes, category=None):
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,40}', item_id):
            raise ValueError('물품 ID는 영문·숫자·하이픈·밑줄 1~40자로 입력하세요.')
        result = self.observation(observation_id)
        if index < 0 or index >= len(result['items']):
            raise ValueError('검출 항목 번호가 올바르지 않습니다.')
        obj = result['items'][index]
        if obj.get('quality') != 'accepted' or not obj.get('_embedding'):
            raise ValueError('박스 검사를 통과하고 임베딩이 생성된 항목만 등록할 수 있습니다.')
        from .config import CLASSES
        category=category or obj['category']
        if category not in CLASSES:
            raise ValueError('등록할 실제 품목을 선택하세요.')
        with self.lock, self.connect() as db:
            old = db.execute('SELECT category FROM items WHERE id=?', (item_id,)).fetchone()
            if old and old['category'] != category:
                raise ValueError('같은 ID에 다른 품목을 합칠 수 없습니다.')
            db.execute('INSERT INTO items VALUES(?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET name=excluded.name, notes=excluded.notes',
                       (item_id, name or item_id, category, notes, time.time()))
            before = db.total_changes
            db.execute('INSERT OR IGNORE INTO refs VALUES(?,?,?,?,?,?,?)',
                       (uuid.uuid4().hex, item_id, obj['_hash'], obj['crop'], json.dumps(obj['_embedding']),
                        json.dumps(obj.get('features', {}), ensure_ascii=False), MODEL_IDS['sig']))
            added = db.total_changes > before
        return {'id': item_id, 'added_reference': added}

    # v0.2.59: registry editing (user: registered items could not be edited)
    def _check_id(self, item_id):
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,40}', item_id or ''):
            raise ValueError('물품 ID는 영문·숫자·하이픈·밑줄 1~40자로 입력하세요.')

    def update_item(self, item_id, name, notes, category):
        from .config import CLASSES
        if category not in CLASSES:raise ValueError('품목(카테고리)을 선택하세요.')
        name=(name or '').strip()[:100] or item_id;notes=(notes or '')[:500]
        with self.lock, self.connect() as db:
            if not db.execute('SELECT 1 FROM items WHERE id=?',(item_id,)).fetchone():raise ValueError('등록 물품을 찾지 못했습니다.')
            db.execute('UPDATE items SET name=?, notes=?, category=? WHERE id=?',(name,notes,category,item_id))
        return {'id':item_id}

    def merge_item(self, source, target):
        """Rename source to target, or merge it into an existing target of the same category."""
        self._check_id(target)
        if source==target:raise ValueError('같은 ID입니다.')
        with self.lock, self.connect() as db:
            src=db.execute('SELECT * FROM items WHERE id=?',(source,)).fetchone()
            if not src:raise ValueError('등록 물품을 찾지 못했습니다.')
            dst=db.execute('SELECT * FROM items WHERE id=?',(target,)).fetchone()
            if dst and dst['category']!=src['category']:raise ValueError('품목이 다른 물품끼리는 합칠 수 없습니다. 먼저 품목을 맞추세요.')
            if not dst:db.execute('INSERT INTO items VALUES(?,?,?,?,?)',(target,src['name'],src['category'],src['notes'],src['created']))
            moved=skipped=0
            for ref in db.execute('SELECT id,hash FROM refs WHERE item_id=?',(source,)).fetchall():
                if db.execute('SELECT 1 FROM refs WHERE item_id=? AND hash=?',(target,ref['hash'])).fetchone():
                    db.execute('DELETE FROM refs WHERE id=?',(ref['id'],));skipped+=1
                else:db.execute('UPDATE refs SET item_id=? WHERE id=?',(target,ref['id']));moved+=1
            db.execute('DELETE FROM items WHERE id=?',(source,))
        return {'id':target,'merged':bool(dst),'moved':moved,'duplicates_removed':skipped}

    def delete_reference(self, ref_id):
        with self.lock, self.connect() as db:
            row=db.execute('SELECT item_id FROM refs WHERE id=?',(ref_id,)).fetchone()
            if not row:raise ValueError('참조 사진을 찾지 못했습니다.')
            db.execute('DELETE FROM refs WHERE id=?',(ref_id,))
            left=db.execute('SELECT COUNT(*) FROM refs WHERE item_id=?',(row['item_id'],)).fetchone()[0]
        return {'id':row['item_id'],'remaining':left}

    def delete_item(self, item_id):
        with self.lock, self.connect() as db:
            if not db.execute('SELECT 1 FROM items WHERE id=?',(item_id,)).fetchone():raise ValueError('등록 물품을 찾지 못했습니다.')
            n=db.execute('DELETE FROM refs WHERE item_id=?',(item_id,)).rowcount
            db.execute('DELETE FROM items WHERE id=?',(item_id,))
        return {'id':item_id,'references_deleted':n}

    def references(self, category=None):
        with self.connect() as db:
            sql = 'SELECT r.*, i.name, i.category, i.notes FROM refs r JOIN items i ON i.id=r.item_id WHERE r.model=?'
            params = [MODEL_IDS['sig']]
            if category:
                sql += ' AND i.category=?'; params.append(category)
            return [dict(r) for r in db.execute(sql, params).fetchall()]

    def items(self):
        with self.connect() as db:
            rows = db.execute('SELECT i.*, COUNT(r.id) AS reference_count FROM items i LEFT JOIN refs r ON r.item_id=i.id GROUP BY i.id ORDER BY i.created DESC').fetchall()
        out = []
        for row in rows:
            item = dict(row)
            refs = self.references(item['category'])
            item['references'] = [{k: r[k] for k in ('id', 'image', 'features')} for r in refs if r['item_id'] == item['id']]
            for ref in item['references']:
                ref['features'] = json.loads(ref['features'])
            out.append(item)
        return out

    def rank(self, embedding, category=None, exclude_hash=None, features=None, limit=5, terms=()):
        query = np.asarray(embedding, dtype=np.float32)
        query /= max(float(np.linalg.norm(query)), 1e-8)
        grouped = {}
        excluded = 0
        for ref in self.references(category):
            if exclude_hash and ref['hash'] == exclude_hash:
                excluded += 1; continue
            vector = np.asarray(json.loads(ref['embedding']), dtype=np.float32)
            if vector.shape != query.shape:
                continue
            score = float(np.dot(query, vector) / max(float(np.linalg.norm(vector)), 1e-8))
            evidence=color_evidence(features,json.loads(ref['features']))
            hit,bonus=name_match(terms,ref['item_id'],ref.get('name',''),ref.get('notes','')) if terms else ([],0.)
            combined=score-evidence['penalty']+bonus
            if ref['item_id'] not in grouped or combined > grouped[ref['item_id']]['matching_score']:
                reason='바탕색 불일치로 0.30 감점 · 가중치 미보정' if evidence['status']=='conflict' else '색상·사진 후보 순위 · 개체 일치 확정 아님'
                if hit: reason=f'이름·설명 일치({", ".join(hit)}) +{bonus:.2f} · '+reason
                grouped[ref['item_id']] = dict(id=ref['item_id'], name=ref['name'], category=ref['category'],
                    similarity=score, matching_score=combined,color_comparison=evidence,image=ref['image'], decision='candidate',
                    name_match=hit,name_bonus=bonus,reason=reason)
        return {'candidates': sorted(grouped.values(), key=lambda r: r['matching_score'], reverse=True)[:limit],
                'excluded_identical_images': excluded, 'decision': 'ambiguous' if grouped else 'no_reference'}
