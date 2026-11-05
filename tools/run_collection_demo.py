"""Start the synthetic collection desk without loading team DB configuration."""
import uvicorn


if __name__ == '__main__':
    print('가상 회수 관리: http://127.0.0.1:8110/collection-desk', flush=True)
    uvicorn.run('agents.center_demo:app', host='127.0.0.1', port=8110,
                proxy_headers=False, access_log=False)
