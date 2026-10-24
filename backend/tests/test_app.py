"""End-to-end tests with every module on its placeholder. These must stay green on main:
they prove the app works no matter which part is unfinished."""

import time

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.schemas import SpeechAudio

PLACEHOLDERS = dict(
    lipreading="mock", correction="passthrough", emotion="neutral", tts="browser", telephony="disabled"
)


@pytest.fixture
def client():
    with TestClient(create_app(Settings(**PLACEHOLDERS))) as c:
        yield c


def speak(client, text="hello there", session_id="test"):
    response = client.post("/api/utterance/text", json={"session_id": session_id, "text": text})
    assert response.status_code == 200, response.text
    return response.json()


def send_video(client, session_id="test"):
    response = client.post(
        "/api/utterance/video",
        data={"session_id": session_id},
        files={"video": ("clip.webm", b"not really a video", "video/webm")},
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_health_lists_every_module(client):
    modules = client.get("/api/health").json()["modules"]
    assert {m["kind"] for m in modules} == {"lipreading", "correction", "emotion", "tts", "telephony"}
    assert all(m["fallback"] for m in modules)


def test_text_utterance(client):
    body = speak(client)
    assert body["text"] == "hello there"
    assert body["audio_url"] is None  # browser TTS
    assert [s["stage"] for s in body["stages"]] == ["correction", "emotion", "tts"]


def test_video_utterance_with_mock_lip_reader(client):
    assert send_video(client)["raw_text"]


def test_unknown_implementation_falls_back_at_startup():
    settings = Settings(**{**PLACEHOLDERS, "correction": "does_not_exist"})
    modules = {m["kind"]: m for m in TestClient(create_app(settings)).get("/api/health").json()["modules"]}
    assert modules["correction"]["active"] == "passthrough"
    assert "unknown implementation" in modules["correction"]["error"]


def test_crashing_module_falls_back_at_runtime(client):
    class Exploding:
        name = "exploding"

        def correct(self, raw_text, context):
            raise RuntimeError("boom")

    client.app.state.pipeline.correction.impl = Exploding()
    body = speak(client)
    stage = next(s for s in body["stages"] if s["stage"] == "correction")
    assert stage["impl"] == "passthrough" and "boom" in stage["error"]
    assert body["text"] == "hello there"


def test_crashing_lip_reader_returns_nothing_instead_of_mock_text(client):
    class Exploding:
        name = "exploding"

        def transcribe(self, video_path):
            raise RuntimeError("boom")

    client.app.state.pipeline.lipreading.impl = Exploding()
    body = send_video(client)
    assert body["text"] == "" and "boom" in body["stages"][0]["error"]


def test_synthesized_audio_is_served(client):
    class FakeTTS:
        name = "fake"

        def synthesize(self, text, emotion):
            return SpeechAudio(data=b"fake-mp3", mime_type="audio/mpeg")

    client.app.state.pipeline.tts.impl = FakeTTS()
    audio = client.get(speak(client)["audio_url"])
    assert audio.status_code == 200 and audio.content == b"fake-mp3"


def test_session_keeps_conversation_history(client):
    speak(client, "first", session_id="s1")
    speak(client, "second", session_id="s1")
    turns = client.get("/api/session/s1").json()["turns"]
    assert [t["text"] for t in turns] == ["first", "second"]
    client.post("/api/session/s1/reset")
    assert client.get("/api/session/s1").json()["turns"] == []


def test_call_endpoints_answer_503_while_telephony_is_disabled(client):
    response = client.post("/api/call/start", json={"session_id": "s", "to": "+15550000000"})
    assert response.status_code == 503


def test_utterances_are_said_into_an_active_call(client):
    said = []

    class FakePhone:
        name = "fake"
        router = None

        def start_call(self, session, to):
            return "call-1"

        def hang_up(self, session):
            pass

        def say(self, session, result):
            said.append(result.text)

    client.app.state.pipeline.telephony.impl = FakePhone()
    started = client.post("/api/call/start", json={"session_id": "c", "to": "+15550000000"})
    assert started.json() == {"call_id": "call-1"}
    assert client.get("/api/session/c").json()["call_active"] is True

    speak(client, "hello", session_id="c")
    deadline = time.time() + 2  # `say` runs in the background after the response
    while not said and time.time() < deadline:
        time.sleep(0.01)
    assert said == ["hello"]

    client.post("/api/call/hangup", json={"session_id": "c"})
    assert client.get("/api/session/c").json()["call_active"] is False


def test_frontend_is_served(client):
    response = client.get("/")
    assert response.status_code == 200 and "Silent Speech" in response.text
