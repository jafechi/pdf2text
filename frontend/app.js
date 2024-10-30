// frontend/app.js

let tasks = {};
let ws;
let username = '';
let isConnected = false;

document.addEventListener('DOMContentLoaded', () => {
    const uploadForm = document.getElementById('uploadForm');
    const fileSection = document.getElementById('fileSection');
    const usernameInput = document.getElementById('username');
    const connectButton = document.getElementById('connectButton');
    const changeUsernameButton = document.getElementById('changeUsername');
    const usernameDisplay = document.getElementById('usernameDisplay');

    // Initially hide file upload section and change username button
    fileSection.style.display = 'none';
    changeUsernameButton.style.display = 'none';

    // Handle username connection
    connectButton.addEventListener('click', (event) => {
        event.preventDefault();
        username = usernameInput.value.trim();
        if (!username) {
            alert('Please enter a username.');
            return;
        }

        // Initialize WebSocket connection
        initiateWebSocket();

        // Update UI to show file section and hide username input
        fileSection.style.display = 'block';
        document.getElementById('usernameSection').style.display = 'none';
        changeUsernameButton.style.display = 'block';
        usernameDisplay.textContent = username;
    });

    // Handle username change
    changeUsernameButton.addEventListener('click', () => {
        // Reset everything
        if (ws) {
            ws.close();
        }
        tasks = {};
        isConnected = false;
        username = '';

        // Reset UI
        updateTaskTable();
        fileSection.style.display = 'none';
        document.getElementById('usernameSection').style.display = 'block';
        changeUsernameButton.style.display = 'none';
        usernameInput.value = '';
        usernameDisplay.textContent = '';
    });

    // Handle file upload
    uploadForm.addEventListener('submit', async (event) => {
        event.preventDefault();
        if (!isConnected) {
            alert('Please connect with a username first.');
            return;
        }

        const fileInput = document.getElementById('fileInput');
        const files = fileInput.files;
        if (files.length === 0) {
            alert('Please select one or more PDF files.');
            return;
        }

        for (let file of files) {
            await uploadFile(file);
        }

        // Clear file input after upload
        fileInput.value = '';
    });
});

async function uploadFile(file) {
    try {
        // Step 1: Get presigned URL and upload_id
        const presignedResponse = await fetch('http://localhost:8000/generate_presigned_url', {
            method: 'POST'
        });
        const presignedData = await presignedResponse.json();
        const { upload_url, upload_id } = presignedData;

        // Add task to tracking with initial status
        tasks[upload_id] = {
            filename: file.name,
            status: 'Uploading',
            upload_id: upload_id
        };
        updateTaskTable();

        // Step 2: Upload file to S3 using presigned POST
        const formData = new FormData();
        Object.entries(upload_url.fields).forEach(([key, value]) => {
            formData.append(key, value);
        });
        formData.append('file', file);

        const uploadResponse = await fetch(upload_url.url, {
            method: 'POST',
            body: formData
        });

        if (!uploadResponse.ok) {
            throw new Error('Failed to upload to S3');
        }

        // Update status to processing
        tasks[upload_id].status = 'Processing';
        updateTaskTable();

        console.log(upload_id);
        console.log(username);

        const requestBody = JSON.stringify({
            upload_id: upload_id,
            client_id: username
        });
        console.log('Request body:', requestBody);

        const completeResponse = await fetch('http://localhost:8000/upload_complete', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: requestBody
        });

        const completeData = await completeResponse.json();
        tasks[upload_id].task_id = completeData.task_id;
        updateTaskTable();

    } catch (error) {
        console.error('Error during upload process:', error);
        // Update task status to error
        if (tasks[upload_id]) {
            tasks[upload_id].status = 'Error';
            tasks[upload_id].error = error.message;
            updateTaskTable();
        }
        alert(`Error uploading file: ${file.name}`);
    }
}

function updateTaskTable() {
    const taskTableBody = document.querySelector('#taskTable tbody');
    taskTableBody.innerHTML = '';

    for (let [id, task] of Object.entries(tasks)) {
        const row = document.createElement('tr');
        const statusClass = `task-status ${task.status.toLowerCase()}`;

        // Task/Upload ID
        const idCell = document.createElement('td');
        idCell.textContent = task.task_id || id;
        row.appendChild(idCell);

        // Filename
        const filenameCell = document.createElement('td');
        filenameCell.textContent = task.filename;
        row.appendChild(filenameCell);

        // Status
        const statusCell = document.createElement('td');
        statusCell.textContent = task.status;
        statusCell.className = statusClass;
        row.appendChild(statusCell);

        // Download Cell
        const downloadCell = document.createElement('td');
        if (task.status === 'completed') {
            const downloadButton = document.createElement('button');
            downloadButton.textContent = 'Download';
            downloadButton.className = 'btn btn-sm btn-success';
            downloadButton.onclick = () => getDownloadUrl(task.upload_id);
            downloadCell.appendChild(downloadButton);
        } else if (task.status === 'Uploading' || task.status === 'Processing') {
            const spinner = document.createElement('div');
            spinner.className = 'spinner-border spinner-border-sm';
            spinner.setAttribute('role', 'status');
            downloadCell.appendChild(spinner);
        } else if (task.status === 'Error') {
            const errorText = document.createElement('small');
            errorText.className = 'text-danger';
            errorText.textContent = task.error || 'Processing failed';
            downloadCell.appendChild(errorText);
        }
        row.appendChild(downloadCell);

        taskTableBody.appendChild(row);
    }
}

async function getDownloadUrl(upload_id) {
    try {
        const response = await fetch('http://localhost:8000/generate_download_url', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ upload_id: upload_id })
        });

        if (!response.ok) {
            const errorData = await response.json();
            throw new Error(errorData.detail || 'Failed to get download URL');
        }

        const data = await response.json();
        // Open the download URL in a new tab
        window.open(data.download_url, '_blank');
    } catch (error) {
        console.error('Error getting download URL:', error);
        alert('Error getting download URL: ' + error.message);
    }
}


function initiateWebSocket() {
    if (ws && ws.readyState === WebSocket.OPEN) {
        ws.close();
    }

    ws = new WebSocket(`ws://localhost:8000/ws/${encodeURIComponent(username)}`);

    ws.onopen = () => {
        console.log('WebSocket connection established');
        isConnected = true;
    };

    ws.onmessage = (event) => {
        const data = JSON.parse(event.data);
        const { task_id, status, upload_id } = data;

        if (tasks[upload_id]) {
            tasks[upload_id].status = status;
            tasks[upload_id].task_id = task_id;
            updateTaskTable();
        }
    };

    ws.onerror = (error) => {
        console.error('WebSocket error:', error);
        isConnected = false;
    };

    ws.onclose = () => {
        console.log('WebSocket connection closed');
        isConnected = false;
    };
}