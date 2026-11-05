"""Process-local generation option for controlled repetition experiments."""


def install_no_repeat(model, size):
    if size < 2:
        raise ValueError('Experimental n-gram size must be at least 2')
    original = model.generate

    def generate(*args, **kwargs):
        if 'no_repeat_ngram_size' in kwargs:
            raise ValueError('Upstream already sets no_repeat_ngram_size; review before overriding')
        return original(*args, no_repeat_ngram_size=size, **kwargs)

    model.generate = generate
