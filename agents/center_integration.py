"""Opt-in LF-9 integration; never installs schema, sends alerts or drives robots."""
import os
from pathlib import Path
from urllib.parse import urlsplit
from agents.admin_auth import COOKIE

PREFIX = '/api/admin/center'


def enabled(name):
    return os.environ.get(name, '').strip().lower() in ('1', 'true', 'yes', 'on')


def environment_services():
    from center.collections import CollectionStore
    from center.statistics import Statistics
    from center.places import Places

    def connect(name):
        dsn = os.environ.get(name)
        if not dsn:
            return None
        def open_connection():
            import psycopg
            return psycopg.connect(dsn, connect_timeout=3)
        return open_connection
    write, read = connect('DATABASE_URL'), connect('LF_STATS_DATABASE_URL')
    return {'collections': CollectionStore(write) if write else None,
            'statistics': Statistics(read) if read else None,
            'places': Places(write) if write else None}


def add_center_integration(app, auth, *, service, services=None):
    injected = services is not None
    active = injected or enabled('TOWER_CENTER')

    @app.get('/api/admin/center-enabled')
    def feature_status():
        return {'enabled': active and auth.enabled}

    if not active:
        return
    from fastapi import Depends, HTTPException, Request
    from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
    from agents.center_api import create_app

    def authorize(request: Request):
        # Existing tower APIs allow unlocked demos. This new DB path does not.
        if not auth.enabled:
            raise HTTPException(503, '회수 관리를 사용하려면 관리자 로그인이 설정되어야 합니다')
        if not injected and (not enabled('TOWER_DB') or enabled('TOWER_SIM') or getattr(service, 'world', None) is not None):
            raise HTTPException(503, '실제 DB 모드에서만 회수 관리를 연결할 수 있습니다')
        if not auth.allowed(request.cookies.get(COOKIE, ''), request.headers.get('x-admin-key', '')):
            raise HTTPException(401, '관리자 로그인이 필요합니다')
        if request.method not in ('GET', 'HEAD', 'OPTIONS'):
            origins = request.headers.getlist('origin')
            expected = urlsplit(str(request.url))
            if len(origins) > 1:
                raise HTTPException(403, '같은 서버 화면에서 요청해주세요')
            if origins:
                origin = urlsplit(origins[0])
                if (origin.scheme, origin.netloc.lower(), origin.path) != (expected.scheme, expected.netloc.lower(), ''):
                    raise HTTPException(403, '같은 서버 화면에서 요청해주세요')
            if request.headers.get('sec-fetch-site') == 'cross-site':
                raise HTTPException(403, '같은 서버 화면에서 요청해주세요')

    stores = services if injected else environment_services()
    child = create_app(**stores, authorize_dependency=authorize)

    @child.exception_handler(Exception)
    async def unavailable(request, error):
        return JSONResponse({'detail': '회수 DB 연결·필수 스키마·권한을 확인해주세요. 작업 결과가 불명확하면 같은 요청 번호로 확인하세요.'}, status_code=503,
                            headers={'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff'})

    @child.middleware('http')
    async def private_response(request, call_next):
        response = await call_next(request)
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self'; style-src 'self'; object-src 'none'; frame-ancestors 'self'; base-uri 'none'"
        return response

    root = Path(__file__).resolve().parents[1] / 'web/center-operations'

    @child.get('/desk', dependencies=[Depends(authorize)])
    def desk():
        return FileResponse(root / 'index.html')

    @child.get('/desk.js', dependencies=[Depends(authorize)])
    def script():
        return FileResponse(root / 'desk.js', media_type='application/javascript')

    @child.get('/desk.css', dependencies=[Depends(authorize)])
    def styles():
        return FileResponse(root / 'desk.css', media_type='text/css')

    @child.get('/dashboard', dependencies=[Depends(authorize)])
    def dashboard():
        store = stores.get('collections')
        if store is None:
            raise HTTPException(503, '회수 DB 연결이 설정되지 않았습니다')
        return store.dashboard()

    @child.get('/readiness', dependencies=[Depends(authorize)])
    def readiness():
        from center.readiness import check_readiness
        return check_readiness(getattr(stores.get('collections'), 'connect', None),
                               getattr(stores.get('statistics'), 'connect', None))

    app.mount(PREFIX, child)

    @app.get('/center', dependencies=[Depends(authorize)])
    def center_page():
        return RedirectResponse(PREFIX + '/desk')
