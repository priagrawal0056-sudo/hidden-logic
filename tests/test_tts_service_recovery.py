import base64
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import requests
import service_limits
import tts


def response(status=200, data=None):
    result=Mock(status_code=status)
    result.json.return_value=data if data is not None else {'candidates':[{'content':{
        'parts':[{'inlineData':{'data':base64.b64encode(b'\x00\x00'*20).decode()}}]}}]}
    return result


class TTSServiceRecoveryTests(unittest.TestCase):
    def test_temporary_http_failure_recovers_in_same_voice_and_complete_script(self):
        script='One complete script.'
        words=[{'word':'One','start':0,'end':.3}]
        with tempfile.TemporaryDirectory() as directory:
            voice=str(Path(directory)/'voice.mp3')
            with patch('requests.post',side_effect=[response(503),response()]) as post, \
                 patch.object(tts,'_TTS_CFG',{'gemini_voice':'Orus'}), \
                 patch.object(tts,'_ffmpeg',return_value='ffmpeg'), \
                 patch.object(tts.subprocess,'run'), patch.object(tts,'_apply_speed'), \
                 patch.object(tts,'_align_with_whisper',return_value=words):
                self.assertEqual(tts._try_gemini_tts(script,voice,voice+'.timings.json','private-test-key'),words)
            self.assertEqual(post.call_count,2)
            for call in post.call_args_list:
                body=call.kwargs['json']
                self.assertTrue(body['contents'][0]['parts'][0]['text'].endswith(script))
                self.assertEqual(body['generationConfig']['speechConfig']['voiceConfig']['prebuiltVoiceConfig']['voiceName'],'Orus')
            self.assertEqual(json.loads(Path(voice+'.service.json').read_text())['attempts'][-1]['status'],'audio_received')

    def test_exhausted_server_requests_remain_retryable_without_fake_quota_classification(self):
        with tempfile.TemporaryDirectory() as directory, patch('requests.post',return_value=response(503)) as post:
            voice=str(Path(directory)/'voice.mp3')
            with self.assertRaisesRegex(service_limits.TransientServiceError,'HTTP 503') as error:
                tts._try_gemini_tts('Test.',voice,voice+'.json','private-test-key')
            self.assertTrue(service_limits.is_retryable(error.exception))
            self.assertEqual(post.call_count,2)
            diagnostic=Path(voice+'.service.json').read_text()
            self.assertNotIn('private-test-key',diagnostic)
            self.assertNotIn('https:',diagnostic)

    def test_network_timeouts_preserve_failure_type_and_hide_request_details(self):
        with tempfile.TemporaryDirectory() as directory, patch('requests.post',side_effect=requests.Timeout('https://secret/?key=private-test-key')) as post:
            voice=str(Path(directory)/'voice.mp3')
            with self.assertRaisesRegex(service_limits.TransientServiceError,'Timeout') as error:
                tts._try_gemini_tts('Test.',voice,voice+'.json','private-test-key')
            self.assertNotIn('private-test-key',str(error.exception)+Path(voice+'.service.json').read_text())
            self.assertEqual(post.call_count,2)

    def test_malformed_audio_never_becomes_unavailable_generic_failure(self):
        for payload in ([], {'candidates':[]}, {'candidates':[{'finishReason':'MAX_TOKENS'}]}):
            with self.subTest(payload=payload), tempfile.TemporaryDirectory() as directory, \
                 patch('requests.post',return_value=response(data=payload)) as post:
                voice=str(Path(directory)/'voice.mp3')
                with self.assertRaises(service_limits.ResponseFormatError):
                    tts._try_gemini_tts('Test.',voice,voice+'.json','private-test-key')
                self.assertEqual(post.call_count,2)
                self.assertFalse(Path(voice).exists())

    def test_daily_quota_stops_after_one_request_and_keeps_explicit_classification(self):
        data={'error':{'details':[{'violations':[{'quotaId':'GenerateRequestsPerDayPerProject'}]}]}}
        with tempfile.TemporaryDirectory() as directory, service_limits.session(), \
             patch('requests.post',return_value=response(429,data)) as post:
            voice=str(Path(directory)/'voice.mp3')
            with self.assertRaises(service_limits.ServiceUnavailable) as error:
                tts._try_gemini_tts('Test.',voice,voice+'.json','private-test-key')
            self.assertEqual(error.exception.limit_kind,'daily')
            self.assertEqual(post.call_count,1)
            self.assertEqual(json.loads(Path(voice+'.service.json').read_text())['attempts'][0]['limit_kind'],'daily')


if __name__=='__main__':unittest.main()
