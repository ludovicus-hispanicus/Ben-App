const { app, BrowserWindow, protocol } = require('electron');
if (require('electron-squirrel-startup')) app.quit();
const path = require('path');
const fs = require('fs');
const { spawn } = require('child_process');
const http = require('http');

let mainWindow;
let pythonProcess;
let angularProcess;

// Configuration
const PYTHON_SERVER_PORT = 5001;
const ANGULAR_DEV_PORT = 4200;
const OLLAMA_URL = 'http://localhost:11434';
const SERVER_URL = `http://localhost:${PYTHON_SERVER_PORT}`;

const IS_PACKAGED = app.isPackaged;

// ── Path helpers ──────────────────────────────────────────────────────────────

function getResourcePath(relativePath) {
    if (IS_PACKAGED) {
        return path.join(process.resourcesPath, relativePath);
    }
    return path.join(__dirname, '..', relativePath);
}

function getAngularDistPath() {
    return getResourcePath(path.join('uni-app'));
}

function getPythonServerPath() {
    if (IS_PACKAGED) {
        return path.join(process.resourcesPath, 'cured-server', 'cured-server.exe');
    }
    return null; // dev mode uses system python
}

function getUserDataPath() {
    return path.join(app.getPath('userData'), 'data');
}

// ── Register custom protocol for serving Angular files ────────────────────────

// Must be called before app.ready
protocol.registerSchemesAsPrivileged([
    {
        scheme: 'cured',
        privileges: {
            standard: true,
            secure: true,
            supportFetchAPI: true,
            corsEnabled: true
        }
    }
]);

// ── Window ────────────────────────────────────────────────────────────────────

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

// ── Custom protocol handler for packaged Angular app ──────────────────────────

function registerCustomProtocol() {
    const distPath = getAngularDistPath();

    protocol.handle('cured', (request) => {
        const url = new URL(request.url);
        let filePath = path.join(distPath, decodeURIComponent(url.pathname));

        // If the path doesn't point to a file, serve index.html (SPA routing)
        if (!fs.existsSync(filePath) || fs.statSync(filePath).isDirectory()) {
            filePath = path.join(distPath, 'index.html');
        }

        return new Response(fs.readFileSync(filePath), {
            headers: { 'Content-Type': getMimeType(filePath) }
        });
    });
}

function getMimeType(filePath) {
    const ext = path.extname(filePath).toLowerCase();
    const mimeTypes = {
        '.html': 'text/html',
        '.js': 'application/javascript',
        '.css': 'text/css',
        '.json': 'application/json',
        '.png': 'image/png',
        '.jpg': 'image/jpeg',
        '.jpeg': 'image/jpeg',
        '.gif': 'image/gif',
        '.svg': 'image/svg+xml',
        '.ico': 'image/x-icon',
        '.woff': 'font/woff',
        '.woff2': 'font/woff2',
        '.ttf': 'font/ttf',
        '.eot': 'application/vnd.ms-fontobject',
        '.otf': 'font/otf',
    };
    return mimeTypes[ext] || 'application/octet-stream';
}

// ── Server checks ─────────────────────────────────────────────────────────────

function checkServerReady(url) {
    return new Promise((resolve) => {
        http.get(url, (res) => {
            resolve(res.statusCode >= 200 && res.statusCode < 400);
        }).on('error', () => {
            resolve(false);
        });
    });
}

function checkOllama() {
    return new Promise((resolve) => {
        http.get(`${OLLAMA_URL}/api/tags`, (res) => {
            resolve(res.statusCode === 200);
        }).on('error', () => {
            resolve(false);
        });
    });
}

// ── Start Python backend ─────────────────────────────────────────────────────

function startPythonServer() {
    console.log('Starting Python server...');
    updateStatus('Starting backend server...');

    const storagePath = getUserDataPath();
    os.makedirs && fs.mkdirSync(storagePath, { recursive: true });

    const serverEnv = {
        ...process.env,
        APP_ENV: 'prod',
        APP_DEBUG: 'False',
        APP_PORT: PYTHON_SERVER_PORT.toString(),
        STORAGE_PATH: storagePath,
        ALGORITHM: 'HS256',
        LOG_LEVEL: 'INFO'
    };

    if (IS_PACKAGED) {
        // Launch bundled PyInstaller executable
        const serverExe = getPythonServerPath();
        console.log(`Launching bundled server: ${serverExe}`);

        pythonProcess = spawn(serverExe, [], {
            env: serverEnv,
            stdio: ['pipe', 'pipe', 'pipe']
        });
    } else {
        // Dev mode: use system Python
        const pythonCmd = process.platform === 'win32' ? 'python' : 'python3';
        const serverPath = path.join(__dirname, '..', 'server', 'src');

        pythonProcess = spawn(
            pythonCmd,
            ['-m', 'uvicorn', 'main:app', '--host', '0.0.0.0', '--port', PYTHON_SERVER_PORT.toString()],
            {
                cwd: serverPath,
                shell: true,
                env: serverEnv
            }
        );
    }

    pythonProcess.stdout.on('data', (data) => {
        const msg = data.toString().trim();
        console.log(`Python: ${msg}`);
        appendLog(msg);
    });

    pythonProcess.stderr.on('data', (data) => {
        const msg = data.toString().trim();
        console.log(`Python: ${msg}`);
        appendLog(msg);
        if (msg.includes('Uvicorn running')) {
            updateStatus('Backend server is ready!');
        }
    });

    pythonProcess.on('error', (err) => {
        console.error('Failed to start Python server:', err);
        updateStatus('Error: Could not start backend server.');
        appendLog(`Error: ${err.message}`);
    });

    pythonProcess.on('close', (code) => {
        console.log(`Python process exited with code ${code}`);
        if (code !== 0 && code !== null) {
            appendLog(`Server exited with code ${code}`);
        }
    });
}

// ── Start Angular (dev mode only) ────────────────────────────────────────────

function startAngularApp() {
    if (IS_PACKAGED) return; // Not needed — served via custom protocol

    console.log('Starting Angular dev server...');
    updateStatus('Starting frontend...');

    const npmCmd = process.platform === 'win32' ? 'npm.cmd' : 'npm';
    const appPath = path.join(__dirname, '..', 'app');

    angularProcess = spawn(npmCmd, ['start'], {
        cwd: appPath,
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

// ── Status updates ────────────────────────────────────────────────────────────

function updateStatus(message) {
    if (mainWindow) {
        mainWindow.webContents.send('update-status', message);
    }
}

function appendLog(message) {
    if (mainWindow) {
        mainWindow.webContents.send('append-log', message);
    }
}

// ── Wait for servers and load app ─────────────────────────────────────────────

async function waitForServersAndLoad() {
    updateStatus('Waiting for backend server...');

    // Wait for Python backend
    let serverReady = false;
    while (!serverReady) {
        serverReady = await checkServerReady(SERVER_URL);
        if (!serverReady) {
            await new Promise(r => setTimeout(r, 1000));
        }
    }
    console.log('Backend server is ready!');

    if (!IS_PACKAGED) {
        // Dev mode: also wait for Angular dev server
        updateStatus('Backend ready, waiting for frontend...');
        let appReady = false;
        while (!appReady) {
            appReady = await checkServerReady(`http://localhost:${ANGULAR_DEV_PORT}`);
            if (!appReady) {
                await new Promise(r => setTimeout(r, 1000));
            }
        }
        console.log('Angular dev server is ready!');
    }

    await loadApp();
}

async function loadApp() {
    const ollamaAvailable = await checkOllama();
    console.log(`Ollama available: ${ollamaAvailable}`);

    if (ollamaAvailable) {
        updateStatus('Ollama detected! VLM OCR available.');
    } else {
        updateStatus('Loading app...');
    }

    // Short delay for status message to display
    await new Promise(r => setTimeout(r, 500));

    if (mainWindow) {
        if (IS_PACKAGED) {
            mainWindow.loadURL('cured://app/index.html');
        } else {
            mainWindow.loadURL(`http://localhost:${ANGULAR_DEV_PORT}`);
        }
    }
}

// ── Process cleanup ───────────────────────────────────────────────────────────

function cleanup() {
    console.log('Cleaning up...');

    if (pythonProcess && !pythonProcess.killed) {
        if (process.platform === 'win32') {
            // On Windows, kill the entire process tree
            spawn('taskkill', ['/pid', pythonProcess.pid.toString(), '/T', '/F'], { shell: true });
        } else {
            pythonProcess.kill('SIGTERM');
        }
        pythonProcess = null;
    }

    if (angularProcess && !angularProcess.killed) {
        if (process.platform === 'win32') {
            spawn('taskkill', ['/pid', angularProcess.pid.toString(), '/T', '/F'], { shell: true });
        } else {
            angularProcess.kill('SIGTERM');
        }
        angularProcess = null;
    }
}

// ── App lifecycle ─────────────────────────────────────────────────────────────

app.whenReady().then(() => {
    if (IS_PACKAGED) {
        registerCustomProtocol();
    }

    createWindow();
    startPythonServer();
    startAngularApp();
    waitForServersAndLoad();

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
