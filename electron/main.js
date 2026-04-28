const { app, BrowserWindow, Menu, dialog, shell, protocol } = require('electron');
// Hidden during splash; restored when the Angular app loads (see installAppMenu)
Menu.setApplicationMenu(null);
if (require('electron-squirrel-startup')) app.quit();
const path = require('path');
const fs = require('fs');
const { spawn } = require('child_process');
const http = require('http');

// Auto-updates via update.electronjs.org (Squirrel.Windows / Squirrel.Mac)
if (app.isPackaged) {
    const { updateElectronApp, UpdateSourceType } = require('update-electron-app');
    const { autoUpdater } = require('electron');
    updateElectronApp({
        updateSource: {
            type: UpdateSourceType.ElectronPublicUpdateService,
            repo: 'ludovicus-hispanicus/Ben-App'
        },
        updateInterval: '24 hours',
        logger: { log: () => {}, info: () => {}, warn: () => {}, error: () => {} } // route via autoUpdater events instead
    });
    autoUpdater.on('checking-for-update', () => appendLog('Checking for updates…'));
    autoUpdater.on('update-available', () => appendLog('Update available — downloading'));
    autoUpdater.on('update-not-available', () => appendLog('Up to date'));
    autoUpdater.on('update-downloaded', () => appendLog('Update ready — restart to install'));
    autoUpdater.on('error', (err) => appendLog(`Update check failed: ${err.message || err}`));
}

let mainWindow;
let pythonProcess;
let angularProcess;
let splashShownAt = 0;
const SPLASH_MIN_MS = 6000; // floor on splash visibility so the carousel cycles

// Configuration
const PYTHON_SERVER_PORT = 5001;
const ANGULAR_DEV_PORT = 4200;
const OLLAMA_URL = 'http://127.0.0.1:11434';
const SERVER_URL = `http://127.0.0.1:${PYTHON_SERVER_PORT}`;

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

// ── Application menu (installed after splash transitions) ────────────────────

function installAppMenu() {
    const template = [
        {
            label: 'File',
            submenu: [
                { role: 'quit' }
            ]
        },
        {
            label: 'Edit',
            submenu: [
                { role: 'undo' },
                { role: 'redo' },
                { type: 'separator' },
                { role: 'cut' },
                { role: 'copy' },
                { role: 'paste' },
                { role: 'selectAll' }
            ]
        },
        {
            label: 'View',
            submenu: [
                { role: 'reload' },
                { role: 'toggleDevTools' },
                { type: 'separator' },
                { role: 'resetZoom' },
                { role: 'zoomIn' },
                { role: 'zoomOut' },
                { type: 'separator' },
                { role: 'togglefullscreen' }
            ]
        },
        {
            label: 'Window',
            submenu: [
                { role: 'minimize' },
                { role: 'close' }
            ]
        },
        {
            label: 'Help',
            submenu: [
                {
                    label: 'About BEn',
                    click: () => {
                        dialog.showMessageBox({
                            type: 'info',
                            title: 'About BEn',
                            message: 'BEn — Babylonian Engine',
                            detail: `Version ${app.getVersion()}\nAI platform for cuneiform analysis\n\n© DigPasts`
                        });
                    }
                },
                {
                    label: 'GitHub Repository',
                    click: () => {
                        shell.openExternal('https://github.com/ludovicus-hispanicus/Ben-App');
                    }
                }
            ]
        }
    ];
    Menu.setApplicationMenu(Menu.buildFromTemplate(template));
}

// ── Window ────────────────────────────────────────────────────────────────────

function createWindow() {
    mainWindow = new BrowserWindow({
        width: 720,
        height: 500,
        center: true,
        resizable: false,
        show: false,
        webPreferences: {
            preload: path.join(__dirname, 'preload.js'),
            nodeIntegration: false,
            contextIsolation: true
        },
        title: "BEn — Babylonian Engine",
        backgroundColor: '#0e1a28',
        icon: path.join(__dirname, 'assets/icon.png')
    });

    mainWindow.webContents.session.clearCache();
    mainWindow.loadFile('loading.html');

    mainWindow.webContents.once('did-finish-load', () => {
        mainWindow.webContents.send('splash-version', app.getVersion());
    });

    mainWindow.once('ready-to-show', () => {
        mainWindow.show();
        splashShownAt = Date.now();
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
            resolve(res.statusCode < 500);
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
    fs.mkdirSync(storagePath, { recursive: true });

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

    appendLog('Backend starting…');

    // Forward Python output to the main-process console for debugging,
    // but only emit curated splash log lines on key events.
    pythonProcess.stdout.on('data', (data) => {
        console.log(`Python: ${data.toString().trim()}`);
    });

    pythonProcess.stderr.on('data', (data) => {
        const msg = data.toString().trim();
        console.log(`Python: ${msg}`);
        if (msg.includes('Uvicorn running')) {
            updateStatus('Backend server is ready');
            appendLog('Backend ready');
        }
    });

    pythonProcess.on('error', (err) => {
        console.error('Failed to start Python server:', err);
        updateStatus('Error: could not start backend');
        appendLog(`Backend error: ${err.message}`);
    });

    pythonProcess.on('close', (code) => {
        console.log(`Python process exited with code ${code}`);
        if (code !== 0 && code !== null) {
            appendLog(`Backend exited (code ${code})`);
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

const MODULE_LABELS = {
    cured: 'CuReD',
    library: 'Library',
    cure: 'CuRe',
    yolo: 'Layout',
    line_segmentation: 'Segmentation'
};

function fetchAndLogModules() {
    return new Promise((resolve) => {
        http.get(`${SERVER_URL}/api/v1/settings/modules`, (res) => {
            let body = '';
            res.on('data', (c) => body += c);
            res.on('end', () => {
                try {
                    const modules = JSON.parse(body);
                    const enabled = Object.entries(modules)
                        .filter(([, on]) => on)
                        .map(([k]) => MODULE_LABELS[k] || k);
                    if (enabled.length) {
                        appendLog(`Modules: ${enabled.join(', ')}`);
                    }
                } catch { /* ignore parse error */ }
                resolve();
            });
        }).on('error', () => resolve());
    });
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
    console.log('Backend server is ready');

    // Surface what's actually available so the user has a useful first impression
    await fetchAndLogModules();

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
        appendLog('Ollama detected — VLM OCR available');
        updateStatus('Ollama detected!');
    } else {
        appendLog('Ollama not detected — cloud OCR only');
        updateStatus('Loading app…');
    }

    // Short delay for status message to display
    await new Promise(r => setTimeout(r, 500));

    // Floor splash visibility so the feature carousel has time to cycle
    const elapsed = Date.now() - splashShownAt;
    const remaining = Math.max(0, SPLASH_MIN_MS - elapsed);
    if (remaining > 0) {
        await new Promise(r => setTimeout(r, remaining));
    }

    if (mainWindow) {
        // Lift the size lock and maximize once we transition out of the splash
        mainWindow.setResizable(true);
        mainWindow.maximize();
        installAppMenu();
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
