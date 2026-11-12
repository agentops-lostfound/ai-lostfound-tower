import json
import queue
import threading
import time
import types
import unittest
import uuid
from unittest.mock import patch
from . import manual_worker


class Input:
    def __init__(self,config):self.config=config;self.q=queue.Queue()
    def readline(self):return json.dumps(self.config)+'\n'
    def __iter__(self):return self
    def __next__(self):
        line=self.q.get()
        if line is None:raise StopIteration
        return json.dumps(line)+'\n'


class WorkerSimulation(unittest.TestCase):
    def run_case(self,case,out_of_range=False):
        names=['shoulder_pan','shoulder_lift','elbow_flex','wrist_flex','wrist_roll','gripper']
        config={'port':'fake','calibration':{n:{'id':i+1,'range_min':1000,'range_max':3000} for i,n in enumerate(names)}}
        positions={i:2000 for i in range(1,7)};torques={i:0 for i in positions};writes=[];events=[];limits={i:500 for i in positions}
        if out_of_range:positions[1]=999
        class Port:
            def __init__(self,*a):self.ser=types.SimpleNamespace(exclusive=False,fileno=lambda:3)
            def openPort(self):return True
            def setBaudRate(self,*a):return True
            def setPacketTimeoutMillis(self,*a):pass
            def closePort(self):pass
        class Packet:
            def read2ByteTxRx(self,port,ident,address):return (limits[ident] if address==48 else 0 if address in [60,69] else positions[ident]),0,0
            def read1ByteTxRx(self,port,ident,address):return torques[ident],0,0
            def write2ByteTxRx(self,port,ident,address,value):
                writes.append((ident,address,value))
                if address==48:limits[ident]=value
                elif torques[ident]:positions[ident]=value
                return 0,0
            def write1ByteTxRx(self,port,ident,address,value):writes.append((ident,address,value));torques[ident]=value;return 0,0
        class FakePath:
            def __init__(self,*a):pass
            def resolve(self,**kw):return self
            def __str__(self):return '/dev/ttyTEST'
            def glob(self,*a):return []
        stdin=Input(config)
        def emit(event,**data):events.append(dict(event=event,**data))
        def until(test):
            end=time.monotonic()+3
            while time.monotonic()<end:
                if test():return
                time.sleep(.01)
            self.fail('가짜 장비 응답 시간 초과')
        def send(action,**kw):
            ident=uuid.uuid4().hex;stdin.q.put(dict(action=action,request_id=ident,**kw))
            until(lambda:any(e.get('request_id')==ident for e in events))
            return next(e for e in events if e.get('request_id')==ident)
        modules={'scservo_sdk':types.SimpleNamespace(PortHandler=Port,PacketHandler=lambda *_:Packet()),
            'fcntl':types.SimpleNamespace(ioctl=lambda *a:None),'termios':types.SimpleNamespace(TIOCEXCL=1)}
        with patch.dict('sys.modules',modules),patch.object(manual_worker,'Path',FakePath),patch.object(manual_worker.sys,'stdin',stdin),patch.object(manual_worker,'emit',emit):
            thread=threading.Thread(target=manual_worker.main);thread.start()
            try:
                until(lambda:any(e['event']=='ready' for e in events));case(send,positions,torques,writes,events,stdin,until)
            finally:
                stdin.q.put(None);thread.join(3)
                self.assertFalse(thread.is_alive())

    def test_readonly_connection_never_enables_or_moves(self):
        def case(send,p,t,w,e,stdin,until):
            self.assertTrue(send('snapshot')['ok']);self.assertEqual(w,[])
        self.run_case(case)

    def test_enable_seeds_current_goal_and_jog_stops(self):
        def case(send,p,t,w,e,stdin,until):
            self.assertTrue(send('enable',joint='shoulder_pan')['ok'])
            self.assertEqual(w[:2],[(1,42,2000),(1,40,1)])
            send('jog',joint='shoulder_pan',direction=1,speed=10,token='first')
            time.sleep(.2);send('halt',token='first');position=p[1];self.assertGreater(position,2000)
            stdin.q.put(dict(action='jog',joint='shoulder_pan',direction=1,speed=10,token='first'))
            time.sleep(.1);self.assertEqual(p[1],position)
            self.assertTrue(all(ident==1 for ident,_,_ in w))
        self.run_case(case)

    def test_expired_input_latches_stop(self):
        def case(send,p,t,w,e,stdin,until):
            send('enable',joint='shoulder_pan');send('jog',joint='shoulder_pan',direction=1,speed=10,token='a')
            until(lambda:any(e['event']=='error' and '만료' in e.get('message','') for e in e))
            self.assertFalse(send('jog',joint='shoulder_pan',direction=1,speed=10,token='b')['ok'])
            self.assertTrue(send('resume')['ok'])
        self.run_case(case)

    def test_out_of_range_enable_rejected(self):
        def case(send,p,t,w,e,stdin,until):
            self.assertFalse(send('enable',joint='shoulder_pan')['ok']);self.assertEqual(w,[])
        self.run_case(case,True)

    def test_multi_axis_goal_and_heartbeat(self):
        def case(send,p,t,w,e,stdin,until):
            send('enable',joint='shoulder_pan');send('enable',joint='shoulder_lift')
            expected={n:2000 for n in ['shoulder_pan','shoulder_lift','elbow_flex','wrist_flex','wrist_roll','gripper']}
            goal=dict(expected,shoulder_pan=2050,shoulder_lift=1950)
            self.assertTrue(send('move',token='motion',target=goal,expected=expected,duration=2)['ok'])
            end=time.monotonic()+3
            while time.monotonic()<end:
                send('move_heartbeat',token='motion');time.sleep(.12)
                if any(x.get('motion',{}).get('status')=='complete' for x in e if x.get('motion')):break
            self.assertLessEqual(abs(p[1]-2050),1);self.assertLessEqual(abs(p[2]-1950),1)
            self.assertTrue(any(x.get('motion',{}).get('status')=='complete' for x in e if x.get('motion')))
        self.run_case(case)

    def test_grip_limit_and_telemetry(self):
        def case(send,p,t,w,e,stdin,until):
            result=send('grip_force',target={'gripper':200},ratio=.2)
            self.assertTrue(result['ok']);self.assertEqual(result['grip_force']['limit_register'],200)
            self.assertAlmostEqual(result['grip_force']['ratio_of_previous'],.4)
            response=send('grip_sample');self.assertTrue(response['ok'],response)
            sample=response['telemetry'];self.assertEqual(sample['torque_limit_register'],200)
            self.assertEqual(w,[(6,48,200)])
        self.run_case(case)

    def test_visual_contact_stops_without_extra_clamp(self):
        def case(send,p,t,w,e,stdin,until):
            send('enable',joint='gripper')
            expected={n:2000 for n in ['shoulder_pan','shoulder_lift','elbow_flex','wrist_flex','wrist_roll','gripper']}
            send('move',token='close',expected=expected,target=dict(expected,gripper=1800),duration=4,grip_contact=True)
            time.sleep(.1)
            result=send('grip_contact_stop',token='close')
            self.assertTrue(result['ok']);self.assertEqual(result['motion']['status'],'contact_candidate')
            self.assertEqual(w[-1],(6,42,p[6]))
        self.run_case(case)
