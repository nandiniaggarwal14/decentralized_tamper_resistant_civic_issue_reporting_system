// Report submission logic with browser MediaRecorder integration
let token = null;
let currentUser = null;

// Recorded Media Blobs
let recordedAudioBlob = null;
let recordedVideoBlob = null;

// MediaRecorder Instances
let audioRecorder = null;
let videoRecorder = null;
let audioChunks = [];
let videoChunks = [];
let videoStream = null;

// Auth Guard Check
async function initializeReport() {
  token = auth.getToken();
  currentUser = await auth.checkAuthGuard(['citizen']);
  
  if (currentUser) {
    // Populate profile card
    document.getElementById('profile-name').textContent = currentUser.full_name;
    document.getElementById('complaint-reporter').value = currentUser.full_name;
    document.getElementById('complaint-contact').value = currentUser.contact || '';
    
    const initials = currentUser.full_name
      .split(' ')
      .map(n => n[0])
      .join('')
      .toUpperCase();
    document.getElementById('profile-initials').textContent = initials.substring(0, 2);
    
    // Auto-fill from GPS helper storage if present
    const helperLat = localStorage.getItem('helper_lat');
    const helperLng = localStorage.getItem('helper_lng');
    if (helperLat && helperLng) {
      document.getElementById('complaint-lat').value = helperLat;
      document.getElementById('complaint-lng').value = helperLng;
      // Clear helper storage
      localStorage.removeItem('helper_lat');
      localStorage.removeItem('helper_lng');
      showAlert('Pre-selected coordinates auto-filled!', false);
    }
  }
}

// Show Alerts
function showAlert(text, isError = false) {
  const banner = document.getElementById('alert-banner');
  const textEl = document.getElementById('alert-text');
  if (banner && textEl) {
    textEl.textContent = text;
    banner.className = `alert-banner ${isError ? 'alert-error' : 'alert-success'}`;
    banner.style.display = 'flex';
    setTimeout(() => { banner.style.display = 'none'; }, 6000);
  }
}

// Geolocation Auto-Detection
function getCurrentGPS() {
  const statusEl = document.getElementById('gps-status');
  if (navigator.geolocation) {
    statusEl.textContent = 'Acquiring lock...';
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        document.getElementById('complaint-lat').value = pos.coords.latitude.toFixed(6);
        document.getElementById('complaint-lng').value = pos.coords.longitude.toFixed(6);
        statusEl.textContent = 'GPS Lock Acquired';
        statusEl.style.color = 'var(--success)';
      },
      (err) => {
        console.warn('Geolocation error:', err);
        statusEl.textContent = 'Access denied. Using CP Center.';
        statusEl.style.color = 'var(--danger)';
        document.getElementById('complaint-lat').value = "28.6315";
        document.getElementById('complaint-lng').value = "77.2167";
      }
    );
  } else {
    statusEl.textContent = 'GPS not supported.';
    statusEl.style.color = 'var(--danger)';
  }
}

// --- Browser Media Capture (Audio) ---
async function startAudioRecording() {
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    audioChunks = [];
    audioRecorder = new MediaRecorder(stream);
    
    audioRecorder.ondataavailable = (e) => {
      if (e.data.size > 0) audioChunks.push(e.data);
    };

    audioRecorder.onstop = () => {
      recordedAudioBlob = new Blob(audioChunks, { type: 'audio/webm' });
      const audioURL = URL.createObjectURL(recordedAudioBlob);
      
      const audioEl = document.getElementById('audio-playback');
      const container = document.getElementById('audio-playback-container');
      audioEl.src = audioURL;
      container.style.display = 'block';
      
      // Stop stream tracks
      stream.getTracks().forEach(track => track.stop());
    };

    audioRecorder.start();
    
    // Toggle UI
    document.getElementById('btn-start-audio').style.display = 'none';
    document.getElementById('btn-stop-audio').style.display = 'inline-flex';
    
    const recIndicator = document.getElementById('recording-status');
    const recText = document.getElementById('recording-status-text');
    recText.textContent = 'Recording Audio...';
    recIndicator.style.display = 'inline-flex';
  } catch (err) {
    console.error('Audio capture blocked:', err);
    showAlert('Microphone permission blocked or not found.', true);
  }
}

function stopAudioRecording() {
  if (audioRecorder && audioRecorder.state !== 'inactive') {
    audioRecorder.stop();
    document.getElementById('btn-start-audio').style.display = 'inline-flex';
    document.getElementById('btn-stop-audio').style.display = 'none';
    document.getElementById('recording-status').style.display = 'none';
    showAlert('Audio capture stored in memory.', false);
  }
}

// --- Browser Media Capture (Video) ---
async function startVideoRecording() {
  try {
    videoStream = await navigator.mediaDevices.getUserMedia({ audio: true, video: true });
    videoChunks = [];
    
    const previewEl = document.getElementById('video-preview');
    previewEl.srcObject = videoStream;
    previewEl.style.display = 'block';

    videoRecorder = new MediaRecorder(videoStream);
    
    videoRecorder.ondataavailable = (e) => {
      if (e.data.size > 0) videoChunks.push(e.data);
    };

    videoRecorder.onstop = () => {
      recordedVideoBlob = new Blob(videoChunks, { type: 'video/webm' });
      previewEl.srcObject = null;
      previewEl.src = URL.createObjectURL(recordedVideoBlob);
      previewEl.controls = true;
      previewEl.muted = false; // unmute for review playback
      
      // Stop camera stream tracks
      if (videoStream) {
        videoStream.getTracks().forEach(track => track.stop());
      }
    };

    videoRecorder.start();

    // Toggle UI
    document.getElementById('btn-start-video').style.display = 'none';
    document.getElementById('btn-stop-video').style.display = 'inline-flex';
    
    const recIndicator = document.getElementById('recording-status');
    const recText = document.getElementById('recording-status-text');
    recText.textContent = 'Recording Video...';
    recIndicator.style.display = 'inline-flex';
  } catch (err) {
    console.error('Video capture blocked:', err);
    showAlert('Camera/Microphone access blocked or not found.', true);
  }
}

function stopVideoRecording() {
  if (videoRecorder && videoRecorder.state !== 'inactive') {
    videoRecorder.stop();
    document.getElementById('btn-start-video').style.display = 'inline-flex';
    document.getElementById('btn-stop-video').style.display = 'none';
    document.getElementById('recording-status').style.display = 'none';
    showAlert('Video capture stored in memory.', false);
  }
}

// --- Form Submissions ---
async function submitReportForm(e) {
  e.preventDefault();
  
  const submitBtn = document.getElementById('btn-submit');
  submitBtn.disabled = true;
  submitBtn.textContent = 'Processing IPFS upload & transaction signing...';

  const formData = new FormData();
  formData.append('title', document.getElementById('complaint-title').value.trim());
  formData.append('description', document.getElementById('complaint-desc').value.trim());
  formData.append('category', document.getElementById('complaint-category').value);
  formData.append('area', document.getElementById('complaint-area').value.trim());
  formData.append('address', document.getElementById('complaint-address').value.trim());
  formData.append('latitude', parseFloat(document.getElementById('complaint-lat').value));
  formData.append('longitude', parseFloat(document.getElementById('complaint-lng').value));
  formData.append('reporter_name', document.getElementById('complaint-reporter').value.trim());
  formData.append('contact', document.getElementById('complaint-contact').value.trim());

  // Check fallback inputs
  const imgInput = document.getElementById('media-img').files[0];
  const audInput = document.getElementById('media-aud').files[0];
  const vidInput = document.getElementById('media-vid').files[0];

  if (imgInput) formData.append('image', imgInput);
  
  // Attach captured audio blob or fallback file input
  if (recordedAudioBlob) {
    formData.append('audio', recordedAudioBlob, 'captured_audio.webm');
  } else if (audInput) {
    formData.append('audio', audInput);
  }

  // Attach captured video blob or fallback file input
  if (recordedVideoBlob) {
    formData.append('video', recordedVideoBlob, 'captured_video.webm');
  } else if (vidInput) {
    formData.append('video', vidInput);
  }

  try {
    const res = await fetch('/api/issues', {
      method: 'POST',
      headers: { 'Authorization': `Bearer ${token}` },
      body: formData
    });
    
    const data = await res.json();
    if (res.ok && data.success) {
      showAlert('Issue successfully logged on block nodes. Redirecting...', false);
      setTimeout(() => {
        window.location.href = '/citizen.html';
      }, 2000);
    } else {
      showAlert(data.detail || 'Failed to submit complaint.', true);
      submitBtn.disabled = false;
      submitBtn.textContent = 'Upload to IPFS & Submit to Blockchain';
    }
  } catch (err) {
    showAlert('Server connection failure when submitting complaint.', true);
    submitBtn.disabled = false;
    submitBtn.textContent = 'Upload to IPFS & Submit to Blockchain';
  }
}

// Startup
window.addEventListener('load', initializeReport);
