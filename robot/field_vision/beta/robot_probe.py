"""Studio 컨테이너 내부에서 실행하는 단발성 읽기 전용 진단.

SO101.connect()는 서보 설정을 쓰므로 사용하지 않는다.
SDK read1/read2만 호출하며 토크/목표/보정 레지스터를 쓰지 않는다.
"""
import json
import os
from pathlib import Path
import sys


def main():
    cfg=json.load(sys.stdin)
    path=Path(cfg['port']).resolve(strict=True)
    if not str(path).startswith('/dev/tty'): raise ValueError('USB 직렬 장치가 아닙니다.')
    # Do not compete with Studio owners or another serial client.
    for process in Path('/proc').glob('[0-9]*'):
        if process.name==str(os.getpid()): continue
        try:
            for fd in (process/'fd').iterdir():
                try:
                    if fd.resolve()==path: raise RuntimeError('장치를 다른 프로세스가 사용 중입니다. 직접 조회하지 않습니다.')
                except (FileNotFoundError,PermissionError): pass
        except (FileNotFoundError,PermissionError): pass
    from scservo_sdk import PortHandler, PacketHandler
    port=PortHandler(str(path));packet=PacketHandler(0)
    try:
        if not port.openPort(): raise RuntimeError('직렬 포트를 열지 못했습니다.')
        port.ser.exclusive=True
        if not port.setBaudRate(1000000): raise RuntimeError('통신 속도 설정 실패')
        port.setPacketTimeoutMillis(100)
        rows=[]
        for name,cal in cfg['calibration'].items():
            ident=cal['id']
            position,comm,err=packet.read2ByteTxRx(port,ident,56)
            if comm or err: raise RuntimeError(f'{name}: 위치 읽기 실패 ({comm},{err})')
            torque,comm,err=packet.read1ByteTxRx(port,ident,40)
            if comm or err: raise RuntimeError(f'{name}: 토크 상태 읽기 실패 ({comm},{err})')
            lo,hi=cal['range_min'],cal['range_max']
            normal=(position-lo)/(hi-lo)*(100 if name=='gripper' else 200)-(0 if name=='gripper' else 100)
            rows.append({'name':name,'id':ident,'raw_ticks':position,'normalized':normal,
                         'in_calibration_range':lo<=position<=hi,'torque_enabled':bool(torque)})
        print(json.dumps({'joints':rows,'write_commands_sent':0}))
    finally:
        port.closePort()


if __name__=='__main__':
    try: main()
    except Exception as exc:
        print(json.dumps({'error':str(exc)}));sys.exit(1)
