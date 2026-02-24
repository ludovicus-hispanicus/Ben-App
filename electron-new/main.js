const { app, BrowserWindow } = require('electron');
if (require('electron-squirrel-startup')) app.quit();
const path = require('path');
const { spawn, exec } = require('child_process');
const http = require('http');

let mainWindow;
let pythonProcess;
let angularProcess;

// Configuration
const PYTHON_SERVER_PORT = 5001;
const ANGULAR_PORT = 4200;
const OLLAMA_URL = 'http://localhost:11434';
const SERVER_URL = `http://localhost:${PYTHON_SERVER_PORT}`;
const APP_URL = `http://localhost:${ANGULAR_PORT}`;

// Paths (relative to electron-new folder)
const SERVER_PATH = path.join(__dirname, '..', 'server-new', 'src');
const APP_PATH = path.join(__dirname, '..', 'app-new');

function createWindow() {
    mainWindow = new BrowserWindow({
        width: 1200,
        height: 800,
        show: false,
        webPreferences: {
            preload: path.join(__dirname, 'preload.js'),
            nodeIntegration: false,
            contextIsolation: true
        },
        title: "CuReD - Dictionary Curation",
        backgroundColor: '#1e1e1e',
        icon: path.join(__dirname, 'assets/icon.png')
    });

    mainWindow.webContents.session.clearCache();
    mainWindow.loadFile('loading.html');

    mainWindow.once('ready-to-show', () => {
        mainWindow.show();
        mainWindow.maximize();
    });

    mainWindow.on('closed', () => {
        mainWindow = null;
    });
}

// Check if a server is ready
function checkServerReady(url, callback) {
    http.get(url, (res) => {
        if (res.statusCode === 200 || res.statusCode === 301 || res.statusCode === 302 || res.statusCode === 304) {
            callback(true);
        } else {
            callback(false);
        }
    }).on('error', () => {
        callback(false);
    });
}

// Check if Ollama is available
function checkOllama() {
    return new Promise((resolve) => {
        http.get(`${OLLAMA_URL}/api/tags`, (res) => {
            resolve(res.statusCode === 200);
        }).on('error', () => {
            resolve(false);
        });
    });
}

// Start Python backend server
function startPythonServer() {
    console.log('Starting Python server...');
    updateStatus('Starting backend server...');

    // Try to find Python
    const pythonCmd = process.platform === 'win32' ? 'python' : 'python3';

    pythonProcess = spawn(pythonCmd, ['-m', 'uvicorn', 'main:app', '--host', '0.0.0.0', '--port', PYTHON_SERVER_PORT.toString()], {
        cwd: SERVER_PATH,
        shell: true,
        env: {
            ...process.env,
            APP_ENV: 'prod',
            APP_DEBUG: 'False',
            APP_PORT: PYTHON_SERVER_PORT.toString(),
            MONGODB_DATABASE: 'flaskdb',
            MONGODB_USERNAME: 'mongodbuser',
            MONGODB_PASSWORD: 'your_mongodb_root_password',
            MONGODB_HOSTNAME: 'mongodb://localhost:27017/',
            STORAGE_PATH: path.join(__dirname, '..', 'data'),
            SECRET: '2c4fc4e6be22853fec33a243a9327e307dc56f0964d2e89e',
            ALGORITHM: 'HS256',
            LOG_LEVEL: 'INFO'
        }
    });

    pythonProcess.stdout.on('data', (data) => {
        console.log(`Python: ${data}`);
    });

    pythonProcess.stderr.on('data', (data) => {
        console.log(`Python: ${data}`);
        // uvicorn logs to stderr
        if (data.toString().includes('Uvicorn running')) {
            console.log('Python server is running!');
        }
    });

    pythonProcess.on('error', (err) => {
        console.error('Failed to start Python server:', err);
        updateStatus('Error: Python not found. Please install Python 3.8+');
    });

    pythonProcess.on('close', (code) => {
        console.log(`Python process exited with code ${code}`);
    });
}

// Start Angular dev server (for development) or serve built files
function startAngularApp() {
    console.log('Starting Angular app...');
    updateStatus('Starting frontend...');

    // Check if dist folder exists (production build)
    const distPath = path.join(APP_PATH, 'dist', 'app');
    const fs = require('fs');

    if (fs.existsSync(distPath)) {
        // Serve built files using http-server or similar
        console.log('Serving production build...');
        // For now, we'll use ng serve. In production, bundle the dist folder.
    }

    // Use ng serve for development
    const npmCmd = process.platform === 'win32' ? 'npm.cmd' : 'npm';

    angularProcess = spawn(npmCmd, ['start'], {
        cwd: APP_PATH,
        shell: true
    });

    angularProcess.stdout.on('data', (data) => {
        console.log(`Angular: ${data}`);
    });

    angularProcess.stderr.on('data', (data) => {
        console.log(`Angular: ${data}`);
    });

    angularProcess.on('error', (err) => {
        console.error('Failed to start Angular:', err);
        updateStatus('Error: npm not found. Please install Node.js');
    });
}

// Update loading screen status
function updateStatus(message) {
    if (mainWindow) {
        mainWindow.webContents.send('update-status', message);
    }
}

// Wait for both servers to be ready
async function waitForServers() {
    updateStatus('Waiting for servers to start...');

    let serverReady = false;
    let appReady = false;

    // Poll for servers
    const checkInterval = setInterval(() => {
        if (!serverReady) {
            checkServerReady(SERVER_URL, (ready) => {
                if (ready) {
                    serverReady = true;
                    console.log('Backend server is ready!');
                    updateStatus('Backend ready, waiting for frontend...');
                }
            });
        }

        if (!appReady) {
            checkServerReady(APP_URL, (ready) => {
                if (ready) {
                    appReady = true;
                    console.log('Angular app is ready!');
                }
            });
        }

        if (serverReady && appReady) {
            clearInterval(checkInterval);
            loadApp();
        }
    }, 1000);
}

// Load the app in the main window
async function loadApp() {
    // Check Ollama status
    const ollamaAvailable = await checkOllama();
    console.log(`Ollama available: ${ollamaAvailable}`);

    if (ollamaAvailable) {
        updateStatus('Ollama detected! VLM OCR available.');
    } else {
        updateStatus('Loading app (Ollama not detected - using Kraken OCR)...');
    }

    setTimeout(() => {
        if (mainWindow) {
            mainWindow.loadURL(APP_URL);
        }
    }, 500);
}

// Cleanup processes
function cleanup() {
    console.log('Cleaning up...');

    if (pythonProcess) {
        pythonProcess.kill();
        pythonProcess = null;
    }

    if (angularProcess) {
        angularProcess.kill();
        angularProcess = null;
    }
}

// App lifecycle
app.whenReady().then(() => {
    createWindow();

    // Start services
    startPythonServer();
    startAngularApp();
    waitForServers();

    app.on('activate', () => {
        if (BrowserWindow.getAllWindows().length === 0) createWindow();
    });
});

app.on('window-all-closed', () => {
    cleanup();
    if (process.platform !== 'darwin') {
        app.quit();
    }
});

app.on('before-quit', () => {
    cleanup();
});
