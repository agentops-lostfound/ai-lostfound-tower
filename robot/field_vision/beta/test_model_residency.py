import threading,unittest
from unittest.mock import Mock,patch
import torch
from PIL import Image
from .models import Models,retry_gpu

class ResidencyTests(unittest.TestCase):
    def test_oom_retries_once_with_residency_disabled(self):
        m=Models(Mock(),threading.Event());m.release=Mock();seen=[]
        @retry_gpu
        def operation(self):
            seen.append(self.resident_enabled)
            if self.resident_enabled:raise torch.cuda.OutOfMemoryError('test')
            return 42
        self.assertEqual(operation(m),42)
        self.assertEqual(seen,[True,False]);m.release.assert_called_once()

    def test_failed_embedding_attempt_publishes_no_callbacks(self):
        m=Models(Mock(),threading.Event());m.release=Mock();calls=0
        def embed(image,items,callback):
            nonlocal calls
            calls+=1;items[0]['attempt']=calls;callback(items[0],image)
            if calls==1:raise torch.cuda.OutOfMemoryError('test')
        m._embed_items=embed;items=[{'index':0}];callback=Mock()
        m.embed_items(Image.new('RGB',(5,5)),items,callback)
        callback.assert_called_once();self.assertEqual(items[0]['attempt'],2)

    def test_qwen_evicts_resident_models_before_loading(self):
        m=Models(Mock(),threading.Event());model=Mock();m._resident={'owl':(model,Mock())}
        # Cancel at model factory: proves eviction without loading Qwen or allocating GPU.
        with patch('torch.cuda.is_available',return_value=True),patch('transformers.AutoProcessor.from_pretrained',side_effect=RuntimeError('stop')):
            with self.assertRaisesRegex(RuntimeError,'stop'):
                with m.use('qwen'):pass
        model.to.assert_called_once_with('meta');self.assertEqual(m._resident,{})
