const form = document.getElementById('issue-form');
const messageEl = document.getElementById('message');
const listEl = document.getElementById('issue-list');
const submitBtn = document.getElementById('submit-btn');
const locationBtn = document.getElementById('location-btn');
const locationStatus = document.getElementById('location-status');
const latitudeInput = document.getElementById('latitude-input');
const longitudeInput = document.getElementById('longitude-input');

function setLocationStatus(text, isError = false) {
  locationStatus.textContent = text;
  locationStatus.style.color = isError ? '#b91c1c' : '#047857';
}

async function getCurrentLocation() {
  if (!navigator.geolocation) {
    setLocationStatus('Geolocation is not supported by your browser.', true);
    return;
  }

  setLocationStatus('Fetching location...');
  locationBtn.disabled = true;

  try {
    const position = await new Promise((resolve, reject) => {
      navigator.geolocation.getCurrentPosition(resolve, reject, {
        enableHighAccuracy: true,
        timeout: 10000,
        maximumAge: 0,
      });
    });

    const { latitude, longitude } = position.coords;
    latitudeInput.value = latitude;
    longitudeInput.value = longitude;
    setLocationStatus(`Location captured: ${latitude.toFixed(4)}, ${longitude.toFixed(4)}`);
  } catch (error) {
    let message = 'Failed to get location.';
    if (error.code === error.PERMISSION_DENIED) {
      message = 'Location access denied. Please enable it in your browser settings.';
    } else if (error.code === error.POSITION_UNAVAILABLE) {
      message = 'Location information is unavailable.';
    } else if (error.code === error.TIMEOUT) {
      message = 'The request to get user location timed out.';
    }
    setLocationStatus(message, true);
  } finally {
    locationBtn.disabled = false;
  }
}

locationBtn.addEventListener('click', getCurrentLocation);

function showMessage(text, isError = false) {
  messageEl.textContent = text;
  messageEl.style.color = isError ? '#b91c1c' : '#047857';
}

function escapeHtml(value) {
  return String(value)
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#039;');
}

function renderIssues(issues) {
  if (!issues.length) {
    listEl.innerHTML = '<p>No reports yet.</p>';
    return;
  }

  listEl.innerHTML = issues
    .map((issue) => {
      const imagePart = issue.image_url
        ? `<img src="${issue.image_url}" alt="Issue image for ${escapeHtml(issue.title)}" />`
        : '';

      return `
        <article class="issue">
          <h3>${escapeHtml(issue.title)}</h3>
          <p class="meta">Status: ${escapeHtml(issue.status)} • Category: ${escapeHtml(issue.category)} • Area: ${escapeHtml(issue.area)}</p>
          <p>${escapeHtml(issue.description)}</p>
          <p class="meta">Location: ${escapeHtml(issue.location.latitude)}, ${escapeHtml(issue.location.longitude)}</p>
          <p class="meta">Address: ${escapeHtml(issue.address || 'N/A')}</p>
          <p class="meta">Reporter: ${escapeHtml(issue.reporter.name)} ${issue.reporter.contact ? `(${escapeHtml(issue.reporter.contact)})` : ''}</p>
          ${imagePart}
        </article>
      `;
    })
    .join('');
}

async function loadIssues() {
  try {
    const response = await fetch('/api/issues');
    const result = await response.json();
    if (!response.ok) {
      throw new Error(result.detail || 'Failed to fetch issues');
    }
    renderIssues(result.data || []);
  } catch (error) {
    showMessage(error.message, true);
  }
}

form.addEventListener('submit', async (event) => {
  event.preventDefault();
  showMessage('Submitting report...');
  submitBtn.disabled = true;

  try {
    const formData = new FormData(form);

    const response = await fetch('/api/issues', {
      method: 'POST',
      body: formData,
    });

    const result = await response.json();
    if (!response.ok) {
      throw new Error(result.detail || 'Submission failed');
    }

    showMessage('Issue submitted successfully.');
    form.reset();
    await loadIssues();
  } catch (error) {
    showMessage(error.message, true);
  } finally {
    submitBtn.disabled = false;
  }
});

loadIssues();
