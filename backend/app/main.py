import base64, binascii, os, re, uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

DATABASE_URL=os.getenv("DATABASE_URL","postgresql+psycopg://lostfound_app:lostfound_app@localhost:5432/lostfound_app")
UPLOAD_DIR=Path(os.getenv("UPLOAD_DIR","./uploads")); UPLOAD_DIR.mkdir(parents=True,exist_ok=True)
engine=create_engine(DATABASE_URL,pool_pre_ping=True)
SessionLocal=sessionmaker(bind=engine,autoflush=False,autocommit=False)
app=FastAPI(title="AI Lost & Found API",version="0.1.0")

def get_db():
 db=SessionLocal()
 try: yield db
 finally: db.close()

class Finder(BaseModel):
 name: Optional[str]=Field(default=None,max_length=80)
 phone: Optional[str]=Field(default=None,max_length=30)
class ItemCreate(BaseModel):
 machine_id: str=Field(min_length=1,max_length=40)
 place_text: str=Field(min_length=1,max_length=128)
 place_id: Optional[int]=None
 finder: Optional[Finder]=None
 photo: Optional[str]=None
class ClaimCreate(BaseModel):
 item_id: str
 claimant_name: str=Field(min_length=1,max_length=80)
 claimant_phone: str=Field(min_length=1,max_length=30)
 description: Optional[str]=Field(default=None,max_length=2000)

def store_photo(data_url):
 if not data_url: return None
 match=re.fullmatch(r"data:image/(jpeg|png|webp);base64,([A-Za-z0-9+/=]+)",data_url)
 if not match: raise HTTPException(422,"photo는 JPEG/PNG/WEBP data URL이어야 합니다.")
 try: raw=base64.b64decode(match.group(2),validate=True)
 except (binascii.Error,ValueError): raise HTTPException(422,"사진 데이터가 올바르지 않습니다.")
 if len(raw)>5*1024*1024: raise HTTPException(422,"사진은 5MB 이하만 등록할 수 있습니다.")
 ext={"jpeg":"jpg","png":"png","webp":"webp"}[match.group(1)]
 filename=f"{uuid.uuid4().hex}.{ext}"; (UPLOAD_DIR/filename).write_bytes(raw)
 return filename

@app.get("/health")
def health(): return {"status":"ok"}
@app.get("/places")
def places(machine_id: str, db: Session=Depends(get_db)):
 rows=db.execute(text("SELECT id AS place_id,label FROM places WHERE machine_id=:m AND is_active=TRUE ORDER BY usage_count DESC,id"),{"m":machine_id}).mappings().all()
 return [dict(r) for r in rows]
@app.post("/items",status_code=201)
def create_item(p: ItemCreate,db: Session=Depends(get_db)):
 place_text=p.place_text.strip()
 if not place_text: raise HTTPException(422,"발견 장소는 필수입니다.")
 if p.place_id is not None:
  valid=db.execute(text("SELECT 1 FROM places WHERE id=:id AND machine_id=:m AND is_active=TRUE"),{"id":p.place_id,"m":p.machine_id}).first()
  if not valid: raise HTTPException(422,"선택한 장소가 해당 등록기계에 없습니다.")
 photo=store_photo(p.photo); now=datetime.now(timezone.utc)
 item_id=f"{p.machine_id[-1:]}-{now:%Y%m%d}-{uuid.uuid4().hex[:8].upper()}"
 try:
  db.execute(text("""INSERT INTO items(item_id,machine_id,place_id,place_text,finder_name,finder_phone,photo_path)
  VALUES(:item_id,:machine,:place_id,:place_text,:name,:phone,:photo)"""),
  {"item_id":item_id,"machine":p.machine_id,"place_id":p.place_id,"place_text":place_text,
   "name":p.finder.name.strip() if p.finder and p.finder.name else None,
   "phone":p.finder.phone.strip() if p.finder and p.finder.phone else None,"photo":photo})
  if p.place_id: db.execute(text("UPDATE places SET usage_count=usage_count+1 WHERE id=:id"),{"id":p.place_id})
  db.commit()
 except Exception:
  db.rollback()
  if photo: (UPLOAD_DIR/photo).unlink(missing_ok=True)
  raise
 return {"item_id":item_id,"received_at":now.isoformat(),"status":"등록기계 보관","place_text":place_text,"contact_saved":bool(p.finder and (p.finder.name or p.finder.phone))}
@app.get("/items")
def list_items(limit:int=100,db:Session=Depends(get_db)):
 rows=db.execute(text("SELECT item_id,machine_id,place_text,status,created_at FROM items ORDER BY created_at DESC LIMIT :n"),{"n":max(1,min(limit,500))}).mappings().all()
 return [dict(r) for r in rows]
@app.post("/claims",status_code=201)
def create_claim(p:ClaimCreate,db:Session=Depends(get_db)):
 if not db.execute(text("SELECT 1 FROM items WHERE item_id=:id"),{"id":p.item_id}).first(): raise HTTPException(404,"해당 접수 번호를 찾을 수 없습니다.")
 claim_id="C-"+datetime.now(timezone.utc).strftime("%Y%m%d")+"-"+uuid.uuid4().hex[:8].upper()
 db.execute(text("INSERT INTO claims(claim_id,item_id,claimant_name,claimant_phone,description) VALUES(:cid,:iid,:name,:phone,:desc)"),
 {"cid":claim_id,"iid":p.item_id,"name":p.claimant_name,"phone":p.claimant_phone,"desc":p.description})
 db.commit(); return {"claim_id":claim_id,"status":"접수"}
@app.get("/claims")
def list_claims(limit:int=100,db:Session=Depends(get_db)):
 rows=db.execute(text("SELECT claim_id,item_id,claimant_name,status,created_at FROM claims ORDER BY created_at DESC LIMIT :n"),{"n":max(1,min(limit,500))}).mappings().all()
 return [dict(r) for r in rows]
