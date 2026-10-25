import { useCallback, useEffect, useRef, useState } from "react";

// Front camera + one clip per sentence, shared by the live and call screens.
// toggle() starts the camera, then starts / stops a recording; onClip gets the Blob.
// onError gets a message (or null when starting over).
export function useClipRecorder({ onClip, onError }) {
  const streamRef = useRef(null);
  const videoEl = useRef(null);
  // A callback ref, so a preview that mounts later (e.g. a new call) still shows the camera
  const videoRef = useCallback((el) => {
    videoEl.current = el;
    if (el && streamRef.current) el.srcObject = streamRef.current;
  }, []);
  const recorderRef = useRef(null);
  const [cameraOn, setCameraOn] = useState(false);
  const [recording, setRecording] = useState(false);

  // Stop the camera when leaving the screen
  useEffect(() => () => streamRef.current?.getTracks().forEach((t) => t.stop()), []);

  async function startCamera() {
    onError(null);
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: false,
        video: { facingMode: "user", width: { ideal: 640 }, height: { ideal: 480 }, frameRate: { ideal: 25 } },
      });
      streamRef.current = stream;
      if (videoEl.current) videoEl.current.srcObject = stream;
      setCameraOn(true);
    } catch (err) {
      // navigator.mediaDevices is undefined on plain http (except localhost)
      onError(`Camera error: ${err.message}. Phones need HTTPS — see the README for tunnels.`);
    }
  }

  function toggle() {
    if (!cameraOn) return void startCamera();
    if (recording) return void recorderRef.current?.stop();
    const chunks = [];
    // iPhones record at 4-9 Mbps by default: 2.5 (Chrome's default) makes the upload 2-4x smaller
    const rec = new MediaRecorder(streamRef.current, { videoBitsPerSecond: 2_500_000 });
    rec.ondataavailable = (e) => chunks.push(e.data);
    rec.onstop = () => {
      setRecording(false);
      onClip(new Blob(chunks, { type: rec.mimeType }));
    };
    recorderRef.current = rec;
    rec.start();
    setRecording(true);
  }

  return { videoRef, cameraOn, recording, startCamera, toggle };
}
