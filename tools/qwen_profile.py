"""Temporary timing wrappers; no model or generation setting changes."""
from contextlib import contextmanager
from time import perf_counter


@contextmanager
def profile_request(bundle, module, torch):
    stats, saved = {}, []

    def wrap(obj, name, key, inspect=None):
        original = getattr(obj, name)
        saved.append((obj, name, name in vars(obj), vars(obj).get(name)))

        def measured(*args, **kwargs):
            torch.cuda.synchronize()
            start = perf_counter()
            try:
                result = original(*args, **kwargs)
            finally:
                torch.cuda.synchronize()
                stats[key] = stats.get(key, 0.0) + perf_counter() - start
            if inspect:
                inspect(result, kwargs)
            return result

        setattr(obj, name, measured)

    def inputs(result, kwargs):
        stats['input_tokens'] = int(result['input_ids'].shape[-1])
        if 'image_grid_thw' in result:
            stats['image_grid_thw'] = result['image_grid_thw'].tolist()

    def generated(result, kwargs):
        count = int(result.shape[-1] - kwargs['input_ids'].shape[-1])
        stats['output_tokens'] = stats.get('output_tokens', 0) + count
        stats['generate_calls'] = stats.get('generate_calls', 0) + 1

    try:
        wrap(bundle.processor, 'apply_chat_template', 'processor_seconds', inputs)
        wrap(bundle.model, 'generate', 'generate_seconds', generated)
        wrap(bundle.processor, 'batch_decode', 'decode_seconds')
        wrap(module, 'validate_response', 'validation_seconds')
        yield stats
    finally:
        for obj, name, own, value in reversed(saved):
            if own:
                setattr(obj, name, value)
            else:
                delattr(obj, name)
