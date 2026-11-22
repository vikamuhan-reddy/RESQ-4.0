/**
 * RESQ 4.0 Voice & Speech Intelligence Interface
 * Handles real-time microphone recording, Web Audio API waveform visualization,
 * Web Speech API recognition (Tamil & English), MediaRecorder audio upload,
 * and Text-to-Speech synthesis.
 *
 * Fix: Transcripts now buffer only isFinal=true segments (no duplicates).
 * Fix: Audio blob is uploaded to /api/transcribe for server-side Gemini transcription.
 */
class VoiceIntelligenceInterface {
    constructor() {
        this.isRecording = false;
        this.mediaRecorder = null;
        this.audioChunks = [];
        this.audioContext = null;
        this.analyser = null;
        this.animationId = null;
        this.speechRecognition = null;
        this.selectedLanguage = 'en';
        this.onTranscriptCallback = null;
        this.onStatusCallback = null;
        // Buffer for final speech segments only
        this._finalTranscript = '';

        this.initSpeechRecognition();
    }

    initSpeechRecognition() {
        const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
        if (!SpeechRecognition) return;

        this.speechRecognition = new SpeechRecognition();
        this.speechRecognition.continuous = true;
        this.speechRecognition.interimResults = true;
        this.speechRecognition.lang = this.selectedLanguage === 'ta' ? 'ta-IN' : 'en-US';

        this.speechRecognition.onresult = (event) => {
            let interimText = '';
            for (let i = event.resultIndex; i < event.results.length; ++i) {
                const segment = event.results[i][0].transcript;
                if (event.results[i].isFinal) {
                    // Append final segments to our stable buffer
                    this._finalTranscript += (this._finalTranscript ? ' ' : '') + segment.trim();
                } else {
                    interimText += segment;
                }
            }
            // Show final + live interim preview
            const display = this._finalTranscript + (interimText ? ' [' + interimText + ']' : '');
            if (this.onTranscriptCallback && display.trim()) {
                this.onTranscriptCallback(this._finalTranscript || display, false);
            }
        };

        this.speechRecognition.onerror = (e) => {
            if (e.error === 'not-allowed') {
                this._setStatus('Microphone permission denied. Please allow access and retry.', 'error');
            } else if (e.error === 'no-speech') {
                // Ignore — common during pauses
            } else {
                console.warn('Speech recognition warning:', e.error);
            }
        };
    }

    setLanguage(lang) {
        this.selectedLanguage = lang;
        if (this.speechRecognition) {
            this.speechRecognition.lang = lang === 'ta' ? 'ta-IN' : 'en-US';
        }
    }

    _setStatus(message, type = 'info') {
        if (this.onStatusCallback) this.onStatusCallback(message, type);
        console.log(`[VoiceRecorder] ${type.toUpperCase()}: ${message}`);
    }

    async toggleRecording(canvasId, onTranscript, onStatus) {
        this.onTranscriptCallback = onTranscript;
        this.onStatusCallback = onStatus || null;
        if (!this.isRecording) {
            await this.startRecording(canvasId);
            return true;
        } else {
            await this.stopRecording();
            return false;
        }
    }

    async startRecording(canvasId) {
        this._finalTranscript = '';
        this.audioChunks = [];

        if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
            this._setStatus('Microphone not supported in this browser. Please type the report.', 'error');
            this.isRecording = true;
            this.simulateWaveform(canvasId);
            return;
        }

        try {
            const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
            this.isRecording = true;

            // Web Audio API for waveform
            this.audioContext = new (window.AudioContext || window.webkitAudioContext)();
            const source = this.audioContext.createMediaStreamSource(stream);
            this.analyser = this.audioContext.createAnalyser();
            this.analyser.fftSize = 256;
            source.connect(this.analyser);
            this.drawWaveform(canvasId);

            // MediaRecorder for audio upload
            const mimeType = MediaRecorder.isTypeSupported('audio/webm;codecs=opus')
                ? 'audio/webm;codecs=opus'
                : (MediaRecorder.isTypeSupported('audio/webm') ? 'audio/webm' : 'audio/ogg');
            this.mediaRecorder = new MediaRecorder(stream, { mimeType });
            this.mediaRecorder.ondataavailable = (e) => {
                if (e.data.size > 0) this.audioChunks.push(e.data);
            };
            this.mediaRecorder.start(1000); // collect in 1-second chunks

            // Web Speech API for live preview
            if (this.speechRecognition) {
                try { this.speechRecognition.start(); } catch (e) {}
            }

            this._setStatus('Recording... Speak clearly.', 'info');
        } catch (err) {
            if (err.name === 'NotAllowedError') {
                this._setStatus('Microphone permission denied. Please allow access and retry.', 'error');
            } else {
                this._setStatus('Microphone unavailable. Please type the report manually.', 'error');
            }
            console.warn('Microphone error:', err);
            this.isRecording = true;
            this.simulateWaveform(canvasId);
        }
    }

    async stopRecording() {
        this.isRecording = false;
        if (this.animationId) cancelAnimationFrame(this.animationId);

        if (this.speechRecognition) {
            try { this.speechRecognition.stop(); } catch (e) {}
        }

        // Stop MediaRecorder and upload audio
        if (this.mediaRecorder && this.mediaRecorder.state !== 'inactive') {
            await new Promise((resolve) => {
                this.mediaRecorder.onstop = resolve;
                this.mediaRecorder.stop();
            });

            if (this.audioChunks.length > 0) {
                this._setStatus('Uploading audio for transcription...', 'info');
                try {
                    const mimeType = this.mediaRecorder.mimeType || 'audio/webm';
                    const blob = new Blob(this.audioChunks, { type: mimeType });
                    const form = new FormData();
                    form.append('audio', blob, 'recording.webm');

                    const res = await fetch('/api/transcribe', { method: 'POST', body: form });
                    const data = await res.json();

                    if (data.transcript) {
                        this._finalTranscript = data.transcript;
                        if (this.onTranscriptCallback) {
                            this.onTranscriptCallback(data.transcript, true);
                        }
                        this._setStatus('Transcription complete (Gemini Audio).', 'success');
                    } else if (data.fallback === 'manual') {
                        // Server said no API key — use Web Speech result if we have it
                        if (!this._finalTranscript) {
                            this._setStatus(data.error || 'Transcription unavailable — using typed/speech input.', 'warn');
                        } else {
                            this._setStatus('Using browser speech recognition transcript.', 'info');
                            if (this.onTranscriptCallback) {
                                this.onTranscriptCallback(this._finalTranscript, true);
                            }
                        }
                    } else if (data.error) {
                        this._setStatus(data.error, 'warn');
                    }
                } catch (uploadErr) {
                    console.warn('Audio upload failed:', uploadErr);
                    this._setStatus('Audio upload failed. Using browser speech result.', 'warn');
                    if (this._finalTranscript && this.onTranscriptCallback) {
                        this.onTranscriptCallback(this._finalTranscript, true);
                    }
                }
            }
        } else if (this._finalTranscript && this.onTranscriptCallback) {
            // No MediaRecorder (simulation mode) — use Web Speech result
            this.onTranscriptCallback(this._finalTranscript, true);
        }

        if (this.audioContext && this.audioContext.state !== 'closed') {
            try { this.audioContext.close(); } catch (e) {}
        }

        this.audioChunks = [];
        this.mediaRecorder = null;
    }

    drawWaveform(canvasId) {
        const canvas = document.getElementById(canvasId);
        if (!canvas || !this.analyser) return;
        const ctx = canvas.getContext('2d');
        const bufferLength = this.analyser.frequencyBinCount;
        const dataArray = new Uint8Array(bufferLength);

        const render = () => {
            if (!this.isRecording) { ctx.clearRect(0, 0, canvas.width, canvas.height); return; }
            this.animationId = requestAnimationFrame(render);
            this.analyser.getByteFrequencyData(dataArray);
            ctx.fillStyle = '#090e1a';
            ctx.fillRect(0, 0, canvas.width, canvas.height);
            const barWidth = (canvas.width / bufferLength) * 2.5;
            let x = 0;
            for (let i = 0; i < bufferLength; i++) {
                const barHeight = dataArray[i] / 2;
                ctx.fillStyle = `rgb(${barHeight + 40}, 182, 212)`;
                ctx.fillRect(x, canvas.height - barHeight, barWidth, barHeight);
                x += barWidth + 1;
            }
        };
        render();
    }

    simulateWaveform(canvasId) {
        const canvas = document.getElementById(canvasId);
        if (!canvas) return;
        const ctx = canvas.getContext('2d');
        const render = () => {
            if (!this.isRecording) { ctx.clearRect(0, 0, canvas.width, canvas.height); return; }
            this.animationId = requestAnimationFrame(render);
            ctx.fillStyle = '#090e1a';
            ctx.fillRect(0, 0, canvas.width, canvas.height);
            const barCount = 32;
            const barWidth = canvas.width / barCount;
            for (let i = 0; i < barCount; i++) {
                const height = Math.random() * (canvas.height * 0.8);
                ctx.fillStyle = '#f59e0b'; // amber to signal simulation
                ctx.fillRect(i * barWidth, canvas.height - height, barWidth - 2, height);
            }
        };
        render();
    }

    speak(text, lang = 'en') {
        if (!window.speechSynthesis) return;
        window.speechSynthesis.cancel();
        const utterance = new SpeechSynthesisUtterance(text);
        utterance.lang = lang === 'ta' ? 'ta-IN' : 'en-US';
        utterance.rate = 0.95;
        window.speechSynthesis.speak(utterance);
    }
}

const voiceInterface = new VoiceIntelligenceInterface();
