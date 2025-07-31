document.addEventListener('DOMContentLoaded', () => {
  const form = document.getElementById('upload-form');
  const modelTypeSelect = document.getElementById('model_type');
  const modelSelect = document.getElementById('model');
  const progressList = document.getElementById('progress-list');
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

    try {
      const res = await fetch('/upload', { method: 'POST', body: formData });
      const data = await res.json();

      if (!data.job_id) {
        thisProgress.innerText = 'Error: No job_id received';
        thisProgress.style.color = "red";
        return;
      }
//      let jobs = JSON.parse(localStorage.getItem('submittedJobs') || '[]');
//      jobs.push({job_id: data.job_id, filename: file.name});
//      localStorage.setItem('submittedJobs', JSON.stringify(jobs));
      thisProgress.innerText = `Processing ${file.name}...`;
      await checkStatus(data.job_id, file.name, thisProgress);
    } catch (err) {
      console.error(err);3
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
//window.addEventListener('DOMContentLoaded', () => {
//  const jobs = JSON.parse(localStorage.getItem('submittedJobs') || '[]');
//  for (const {job_id, filename} of jobs) {
//    // Recreate per-file progress bar (optional: show "Restoring...")
//    let safeId = "progress_" + filename.replace(/[^a-zA-Z0-9\-_\.]/g, "_");
//    let thisProgress = document.getElementById(safeId);
//    if (!thisProgress) {
//      thisProgress = document.createElement('div');
//      thisProgress.id = safeId;
//      thisProgress.style.fontWeight = "bold";
//      thisProgress.style.color = "gray";
//      thisProgress.style.fontSize = "2em";
//      thisProgress.style.marginBottom = "8px";
//      thisProgress.innerText = `Restoring status for ${filename}...`;
//      document.getElementById('progress-list').appendChild(thisProgress);
//    }
//    checkStatus(job_id, filename, thisProgress);
//  }
//});
