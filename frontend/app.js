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
    uploadForm.addEventListener('submit', (event) => {
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
            uploadFile(file);
        }

        // Clear file input after upload
        fileInput.value = '';
    });
});

function uploadFile(file) {
    const formData = new FormData();
    formData.append('file', file);

    fetch('http://localhost:8000/upload', {
        method: 'POST',
        body: formData
    })
    .then(response => response.json())
    .then(data => {
        const taskId = data.task_id;
        tasks[taskId] = {
            filename: file.name,
            status: 'Processing'
        };
        updateTaskTable();
        sendTaskIdToWebSocket(taskId);
    })
    .catch(error => {
        console.error('Error:', error);
        alert('Error uploading file: ' + file.name);
    });
}

function updateTaskTable() {
    const taskTableBody = document.querySelector('#taskTable tbody');
    taskTableBody.innerHTML = '';
    for (let [taskId, task] of Object.entries(tasks)) {
        const row = document.createElement('tr');
        const statusClass = `task-status ${task.status.toLowerCase()}`;

        // Task ID
        const taskIdCell = document.createElement('td');
        taskIdCell.textContent = taskId;
        row.appendChild(taskIdCell);

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
            const downloadLink = document.createElement('a');
            downloadLink.href = `http://localhost:8000/result/${taskId}`;
            downloadLink.textContent = 'Download';
            downloadLink.className = 'btn btn-sm btn-success';
            downloadLink.target = '_blank';
            downloadCell.appendChild(downloadLink);
        } else if (task.status === 'Processing') {
            const disabledButton = document.createElement('button');
            disabledButton.textContent = 'Download';
            disabledButton.className = 'btn btn-sm btn-secondary disabled';
            disabledButton.disabled = true;
            downloadCell.appendChild(disabledButton);
        } else if (task.status === 'error') {
            const errorText = document.createElement('small');
            errorText.className = 'text-danger';
            errorText.textContent = 'Processing failed';
            downloadCell.appendChild(errorText);
        }
        row.appendChild(downloadCell);

        taskTableBody.appendChild(row);
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
        const taskId = data.task_id;
        if (tasks[taskId]) {
            tasks[taskId].status = data.status;
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

function sendTaskIdToWebSocket(taskId) {
    if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ task_id: taskId }));
    } else {
        console.error('WebSocket is not open. Cannot send task ID.');
    }
}