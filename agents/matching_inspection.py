"""Trusted single-scene LF-5 -> LF-20 inspection; no HTTP, DB, or robot access."""
import json
import threading

from agents.lost_input import checked_text
from matching.hybrid import HybridMatcher
from matching.inspect_sequence import inspect
from matching.korean_query import KoreanFirstParser, extract_korean
from matching.policy import load_config
from matching.query_parser import validate_output


class ModelsRequired(RuntimeError):
    pass


class NoTranslation:
    model_id = 'not_configured'
    init_seconds = 0

    def parse(self, *_args, **_kwargs):
        raise ModelsRequired('translation_required')


class NoEmbedding:
    def prepare(self, _candidates):
        raise ModelsRequired('embedding_required')


def result(status, reason, *, candidate_numbers=(), matched=False):
    return {'status': status, 'reason': reason, 'candidate_numbers': list(candidate_numbers),
            'matching_performed': matched, 'inspection_only': True,
            'scope': 'single_scene_inspection', 'identity_verified': False,
            'reservation_created': False, 'robot_authorized': False,
            'notice': '한 장면의 검사 결과입니다. 실제 습득물 DB 검색·본인 물건 확정·예약·반환 승인이 아닙니다.'}


class MatchingInspection:
    """Models must be explicitly injected; defaults never load/download weights.

    report is a server-owned LF-3 snapshot, not a public upload or a DB inventory.
    Each call uses a fresh bridge, so mutable diagnostics are not shared.
    """
    def __init__(self, parser=None, matcher=None):
        self.parser = parser or KoreanFirstParser(translator=NoTranslation())
        self.matcher = matcher or HybridMatcher(load_config(), offline=True, ranker=NoEmbedding())
        self._lock = threading.Lock()

    def ask(self, question, report):
        question = checked_text(question, '검사할 물건 설명', 500)
        # Translators/rankers may keep mutable buffers; never interleave scenes.
        if not self._lock.acquire(blocking=False):
            return result('inspection_busy', 'inspection_in_progress')
        try:
            return self._ask(question, report)
        finally:
            self._lock.release()

    def _ask(self, question, report):
        # Do not turn unresolved/unsupported item constraints into color-only matches.
        evidence = extract_korean(question)
        if evidence['needs_clarification'] or evidence['match_block_reasons']:
            return result('clarification_needed', 'description_requires_review')
        try:
            if (not isinstance(report, dict) or not isinstance(report.get('objects'), list)
                    or not 1 <= len(report['objects']) <= 50
                    or len(json.dumps(report, allow_nan=False).encode()) > 2_000_000):
                return result('inspection_unavailable', 'invalid_scene')
        except (TypeError, ValueError, RecursionError):
            return result('inspection_unavailable', 'invalid_scene')
        try:
            parsed = self.parser.parse(question)
            validated = validate_output({key: parsed[key] for key in ('features', 'needs_clarification', 'warnings')})
            # A custom parser cannot erase constraints found in the Korean source.
            if (validated['needs_clarification'] or parsed.get('match_block_reasons')
                    or any(validated['features'][key] != evidence['features'][key]
                           for key in ('category', 'colors', 'sticker_status'))):
                return result('clarification_needed', 'description_requires_review')
            parsed = {**parsed, **validated, 'requires_review': True}
            if parsed['features']['free_text'] and isinstance(getattr(self.matcher, 'ranker', None), NoEmbedding):
                return result('feature_models_required', 'embedding_not_configured')
        except ModelsRequired:
            return result('feature_models_required', 'translation_not_configured')
        except (KeyError, ValueError, TypeError, RuntimeError, OSError, ImportError):
            return result('inspection_unavailable', 'description_processing_failed')
        try:
            measured = inspect(report, parsed, self.matcher)
        except (KeyError, ValueError, TypeError, RuntimeError, OSError, ImportError, OverflowError):
            return result('inspection_unavailable', 'scene_processing_failed')
        contract = measured['contract_result']
        if contract['reason'] != 'inspection_only_staff_review_required':
            return result('inspection_unavailable', 'scene_or_matcher_not_ready')
        # No source text, private features, raw IDs, geometry, file paths, or scores.
        numbers = [row['index'] + 1 for row in measured['top3']]
        return result('review_required', 'inspection_requires_confirmation',
                      candidate_numbers=numbers, matched=True)
