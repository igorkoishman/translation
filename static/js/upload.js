document.addEventListener('DOMContentLoaded', () => {
  const form = document.getElementById('upload-form');
  const modelTypeSelect = document.getElementById('model_type');
  const modelSelect = document.getElementById('model');


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
modelTypeSelect.addEventListener('change', () => {
  console.log("Selected model type:", modelTypeSelect.value);
  updateModelOptions();
});
//  modelTypeSelect.addEventListener('change', updateModelOptions);
//  updateModelOptions();

  form.onsubmit = async (e) => {
    e.preventDefault();

    const fileInput = document.getElementById('file-input');
    const langs = document.getElementById('langs').value;
    const model = modelSelect.value;
    const model_type = modelTypeSelect.value;
    const processor = document.getElementById('processor').value;
    const align = document.getElementById('align').checked;

    const formData = new FormData();
    formData.append('file', fileInput.files[0]);
    formData.append('langs', langs);
    formData.append('model', model);
    formData.append('model_type', model_type);
    formData.append('align', align);
    formData.append('processor', processor);
console.log("Submitting model_type:", model_type);
    document.getElementById('progress').innerText = 'Uploading...';
    document.getElementById('result').innerHTML = '';

    try {
      const res = await fetch('/upload', { method: 'POST', body: formData });
      const data = await res.json();

      if (!data.job_id) {
        document.getElementById('progress').innerText = 'Error: No job_id received';
        return;
      }

      document.getElementById('progress').innerText = 'Processing...';
      await checkStatus(data.job_id);
    } catch (err) {
      console.error(err);
      document.getElementById('progress').innerText = 'Upload failed.';
    }
  };

  async function checkStatus(job_id) {
  try {
    const res = await fetch('/status/' + job_id);
    const data = await res.json();

    if (data.status === 'done') {
      let outputHTML = '<p>Download Results:</p>';

      // Filter out non-file keys like 'duration_seconds' and 'status'
      for (const [label, fileName] of Object.entries(data.outputs)) {
        if (
          label === "status" ||
          label === "duration_seconds" ||
          !fileName ||
          typeof fileName !== "string"
        ) continue;  // skip keys that are not files

        outputHTML += `
          <div class="output-link">
            <a href="/download/${fileName}" target="_blank">${label}</a>
          </div>`;
      }

      if (data.duration_seconds) {
        outputHTML += `<p><strong>Processing Time:</strong> ${data.duration_seconds} seconds</p>`;
      }

      document.getElementById('result').innerHTML = outputHTML;
      document.getElementById('progress').innerText = 'Done!';
    } else if (data.status === 'failed') {
      document.getElementById('progress').innerText = 'Processing failed.';
    } else {
      setTimeout(() => checkStatus(job_id), 2000);
    }
  } catch (err) {
    console.error(err);
    document.getElementById('progress').innerText = 'Error checking status.';
  }
}
});
