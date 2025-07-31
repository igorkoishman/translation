document.addEventListener('DOMContentLoaded', () => {
  const form = document.getElementById('upload-form');
  const modelTypeSelect = document.getElementById('model_type');
  const modelSelect = document.getElementById('model');
  const progressDiv = document.getElementById('progress');
  const resultsTable = document.getElementById('results-table');
  const resultsTbody = resultsTable.querySelector('tbody');

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

  // initial model options
  updateModelOptions();

  form.onsubmit = async (e) => {
    e.preventDefault();

    const fileInput = document.getElementById('file-input');
    const file = fileInput.files[0];
    const langs = document.getElementById('langs').value;
    const original_lang = document.getElementById('original_lang').value;
    const model = modelSelect.value;
    const model_type = modelTypeSelect.value;
    const processor = document.getElementById('processor').value;
    const align = document.getElementById('align').checked;

    if (!file) {
      progressDiv.innerText = "No file selected.";
      return;
    }

    progressDiv.innerText = `Uploading ${file.name}...`;

    const formData = new FormData();
    formData.append('file', file);
    formData.append('langs', langs);
    formData.append('original_lang', original_lang);
    formData.append('model', model);
    formData.append('model_type', model_type);
    formData.append('align', align);
    formData.append('processor', processor);

    try {
      const res = await fetch('/upload', { method: 'POST', body: formData });
      const data = await res.json();

      if (!data.job_id) {
        progressDiv.innerText = 'Error: No job_id received';
        return;
      }

      progressDiv.innerText = `Processing ${file.name}...`;
      await checkStatus(data.job_id, file.name);
    } catch (err) {
      console.error(err);
      progressDiv.innerText = 'Upload failed.';
    }
  };

  async function checkStatus(job_id, inputFileName) {
    try {
      const res = await fetch('/status/' + job_id);
      const data = await res.json();

      if (data.status === 'done') {
        progressDiv.innerHTML = `<span style="color:green;font-weight:bold">Done! (${inputFileName})</span>`;
        resultsTable.style.display = ''; // show the table if hidden

        // data.outputs: { label: fullOutputFileName }
        // Example: { "orig": "myfile_123_output_orig.mp4", "orig_srt": "myfile_123_output_orig.srt", ... }
        // Show every output in a new row
        let firstRow = true;
        for (const [label, fullOutputFileName] of Object.entries(data.outputs)) {
          // skip if not a real file name
          if (!fullOutputFileName || typeof fullOutputFileName !== 'string') continue;

          const tr = document.createElement('tr');
          if (firstRow) {
            // Input file cell, only once per upload
            tr.innerHTML = `
              <td rowspan="${Object.keys(data.outputs).length}">${inputFileName}</td>
              <td>${label}</td>
              <td>${fullOutputFileName}</td>
              <td><a href="/download/${fullOutputFileName}" target="_blank">Download</a></td>
              <td rowspan="${Object.keys(data.outputs).length}">${data.duration_seconds || ''}</td>
            `;
            firstRow = false;
          } else {
            // Other outputs for same upload
            tr.innerHTML = `
              <td>${label}</td>
              <td>${fullOutputFileName}</td>
              <td><a href="/download/${fullOutputFileName}" target="_blank">Download</a></td>
            `;
          }
          resultsTbody.appendChild(tr);
        }
      } else if (data.status === 'failed') {
        progressDiv.innerText = 'Processing failed.';
      } else {
        setTimeout(() => checkStatus(job_id, inputFileName), 2000);
      }
    } catch (err) {
      console.error(err);
      progressDiv.innerText = 'Error checking status.';
    }
  }
});
