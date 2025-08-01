document.addEventListener('DOMContentLoaded', () => {
  const form = document.getElementById('upload-form');
  const modelTypeSelect = document.getElementById('model_type');
  const modelSelect = document.getElementById('model');
  const progressList = document.getElementById('progress-list');
  const resultsTable = document.getElementById('results-table');
  const resultsTbody = resultsTable.querySelector('tbody');

  // Track selector elements
  // Make sure these exist in your HTML as shown previously!
  const trackSelectors = document.getElementById('track-selectors');
  const audioTrackSelect = document.getElementById('audio-track');
  const subtitleTrackSelect = document.getElementById('subtitle-track');
  const useSubtitlesOnly = document.getElementById('use-subtitles-only');

  const modelsByBackend = {
    'faster-whisper': ['tiny', 'base', 'small', 'medium', 'large-v1', 'large-v2', 'large-v3', 'large'],
    'openai-whisper': [
      'tiny', 'tiny.en', 'base', 'base.en', 'small', 'small.en', 'medium', 'medium.en',
      'large', 'large-v1', 'large-v2', 'large-v3',
      'large-v3-turbo', 'turbo'
    ]
  };

  function updateModelOptions() {
    const selectedBackend = modelTypeSelect.value;
    const modelOptions = modelsByBackend[selectedBackend] || [];
    modelSelect.innerHTML = '';
    for (const model of modelOptions) {
      const option = document.createElement('option');
      option.value = model;
      option.textContent = model;
      modelSelect.appendChild(option);
    }
  }
  modelTypeSelect.addEventListener('change', updateModelOptions);
  updateModelOptions();

  // ---- TRACK ANALYSIS LOGIC ----
  const fileInput = document.getElementById('file-input');
  fileInput.addEventListener('change', async (e) => {
    const file = fileInput.files[0];
    if (!file) {
      trackSelectors.style.display = "none";
      return;
    }
    const formData = new FormData();
    formData.append('file', file);

    // Reset dropdowns and hide selectors until analysis is complete
    audioTrackSelect.innerHTML = '';
    subtitleTrackSelect.innerHTML = '<option value="">None</option>';
    useSubtitlesOnly.checked = false;
    trackSelectors.style.display = "none";

    try {
      let res = await fetch('/analyze', {method: 'POST', body: formData});
      let data = await res.json();
      let audioCount = 0, subCount = 0;
      data.tracks.forEach(track => {
        if (track.type === 'audio') {
          const label = `#${track.index} - ${track.lang || 'und'} [${track.codec}]${track.default ? ' (default)' : ''}`;
          const opt = document.createElement('option');
          opt.value = track.index;
          opt.textContent = label;
          audioTrackSelect.appendChild(opt);
          audioCount++;
        } else if (track.type === 'subtitle') {
          const label = `#${track.index} - ${track.lang || 'und'} [${track.codec}]${track.default ? ' (default)' : ''}`;
          const opt = document.createElement('option');
          opt.value = track.index;
          opt.textContent = label;
          subtitleTrackSelect.appendChild(opt);
          subCount++;
        }
      });
      if (audioCount + subCount > 0) {
        trackSelectors.style.display = "";
      } else {
        trackSelectors.style.display = "none";
      }
    } catch (err) {
      console.error("Track analysis failed:", err);
      trackSelectors.style.display = "none";
    }
  });

  // ---- FORM SUBMIT LOGIC ----
  form.onsubmit = async (e) => {
    e.preventDefault();

    const file = fileInput.files[0];
    const langs = document.getElementById('langs').value;
    const original_lang = document.getElementById('original_lang').value;
    const model = modelSelect.value;
    const model_type = modelTypeSelect.value;
    const processor = document.getElementById('processor').value;
    const align = document.getElementById('align').checked;
    const burnType = document.getElementById('subtitle_burn_type').value;


    // Track selections
    const audioTrack = audioTrackSelect && audioTrackSelect.value ? audioTrackSelect.value : '';
    const subtitleTrack = subtitleTrackSelect && subtitleTrackSelect.value ? subtitleTrackSelect.value : '';
    const useSubsOnly = useSubtitlesOnly && useSubtitlesOnly.checked;

    if (!file) {
      let errorDiv = document.createElement('div');
      errorDiv.style.color = "red";
      errorDiv.style.fontWeight = "bold";
      errorDiv.innerText = "No file selected.";
      progressList.appendChild(errorDiv);
      return;
    }

    let safeId = "progress_" + file.name.replace(/[^a-zA-Z0-9\-_\.]/g, "_");
    let thisProgress = document.getElementById(safeId);
    if (!thisProgress) {
      thisProgress = document.createElement('div');
      thisProgress.id = safeId;
      thisProgress.style.fontWeight = "bold";
      thisProgress.style.color = "green";
      thisProgress.style.fontSize = "2em";
      thisProgress.style.marginBottom = "8px";
      progressList.appendChild(thisProgress);
    }
    thisProgress.innerText = `Uploading ${file.name}...`;

    const formData = new FormData();
    formData.append('file', file);
    formData.append('langs', langs);
    formData.append('original_lang', original_lang);
    formData.append('model', model);
    formData.append('model_type', model_type);
    formData.append('align', align);
    formData.append('processor', processor);
    formData.append('subtitle_burn_type', burnType);
    // Add track fields if present
    if (audioTrack !== '') formData.append('audio_track', audioTrack);
    if (subtitleTrack !== '') formData.append('subtitle_track', subtitleTrack);
    if (useSubsOnly) formData.append('use_subtitles_only', useSubsOnly);

    try {
      const res = await fetch('/upload', { method: 'POST', body: formData });
      const data = await res.json();

      if (!data.job_id) {
        thisProgress.innerText = 'Error: No job_id received';
        thisProgress.style.color = "red";
        return;
      }
      thisProgress.innerText = `Processing ${file.name}...`;
      await checkStatus(data.job_id, file.name, thisProgress);
    } catch (err) {
      console.error(err);
      thisProgress.innerText = 'Upload failed.';
      thisProgress.style.color = "red";
    }
  };

  async function checkStatus(job_id, inputFileName, thisProgress) {
    try {
      const res = await fetch('/status/' + job_id);
      const data = await res.json();

      if (data.status === 'done') {
        thisProgress.innerHTML = `<span style="color:green;font-weight:bold">Done! (${inputFileName})</span>`;
        resultsTable.style.display = ''; // show the table if hidden

        let firstRow = true;
        const nOutputs = Object.keys(data.outputs).length;
        for (const [label, fullOutputFileName] of Object.entries(data.outputs)) {
          if (!fullOutputFileName || typeof fullOutputFileName !== 'string') continue;
          const tr = document.createElement('tr');
          if (firstRow) {
            tr.innerHTML = `
              <td rowspan="${nOutputs}">${inputFileName}</td>
              <td>${label}</td>
              <td>${fullOutputFileName}</td>
              <td><a href="/download/${fullOutputFileName}" target="_blank">Download</a></td>
              <td rowspan="${nOutputs}">${data.duration_seconds || ''}</td>
            `;
            firstRow = false;
          } else {
            tr.innerHTML = `
              <td>${label}</td>
              <td>${fullOutputFileName}</td>
              <td><a href="/download/${fullOutputFileName}" target="_blank">Download</a></td>
            `;
          }
          resultsTbody.appendChild(tr);
        }
      } else if (data.status === 'failed') {
        thisProgress.innerText = 'Processing failed.';
        thisProgress.style.color = "red";
      } else {
        setTimeout(() => checkStatus(job_id, inputFileName, thisProgress), 2000);
      }
    } catch (err) {
      console.error(err);
      thisProgress.innerText = 'Error checking status.';
      thisProgress.style.color = "red";
    }
  }
});
