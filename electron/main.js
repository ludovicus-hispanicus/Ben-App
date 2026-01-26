const { app, BrowserWindow } = require('electron');
if (require('electron-squirrel-startup')) app.quit();
const path = require('path');
const { spawn, exec } = require('child_process');
const http = require('http');

let mainWindow;
let dockerProcess;
const APP_URL = 'http://localhost:8081';

function createWindow() {
    mainWindow = new BrowserWindow({
        width: 1200,
        height: 800,
        show: false, // Don't show until ready or loading
        webPreferences: {
            preload: path.join(__dirname, 'preload.js'),
            nodeIntegration: false,
            contextIsolation: true
        },
        title: "BEn App",
        backgroundColor: '#1e1e1e',
        icon: path.join(__dirname, 'assets/icon.png') // Optional if icon exists
    });

    // Clear cache to ensure fresh load of the web app
    // Note: Only clear cache, NOT storage - storage contains login tokens
    // Clearing storage would force users to log in every time (hiding CuRe until login)
    mainWindow.webContents.session.clearCache();

    mainWindow.loadFile('loading.html');
    mainWindow.once('ready-to-show', () => {
        mainWindow.show();
        mainWindow.maximize(); // Maximize to ensure all menu items are visible
    });

    mainWindow.on('closed', () => {
        mainWindow = null;
    });
}

// Function to check if the web server is ready
function checkServerReady() {
    http.get(APP_URL, (res) => {
        if (res.statusCode === 200 || res.statusCode === 301 || res.statusCode === 302 || res.statusCode === 304) {
            console.log('Server is ready, loading app...');
            if (mainWindow) {
                mainWindow.loadURL(APP_URL);
            }
        } else {
            console.log(`Server responded with ${res.statusCode}, retrying...`);
            setTimeout(checkServerReady, 2000);
        }
    }).on('error', (e) => {
        console.log('Server not ready yet, retrying...');
        setTimeout(checkServerReady, 2000);
    });
}

// Function to start Docker containers
function startDocker() {
    console.log('Starting Docker via WSL...');

    const wslCommand = 'wsl';
    const args = ['-d', 'Ubuntu', '--', 'docker', 'compose', 'up'];

    // Use the headless setup script based on platform
    let setupCmd, setupArgs;

    if (process.platform === 'win32') {
        let setupPath = path.join(__dirname, 'setup-headless.bat');
        console.log(`Spawning setup script for Windows: ${setupPath}`);
        setupCmd = setupPath;
        setupArgs = [];
    } else {
        // macOS or Linux
        const setupScript = path.join(__dirname, 'setup-mac.sh');
        console.log(`Spawning setup script for Mac/Linux: ${setupScript}`);
        setupCmd = '/bin/bash';
        setupArgs = [setupScript];
    }

    dockerProcess = spawn(setupCmd, setupArgs, {
        cwd: __dirname,
        shell: process.platform === 'win32'
    });

    dockerProcess.stdout.on('data', (data) => {
        const output = data.toString();
        console.log(`Docker: ${output}`);

        // Parse for [PHASE] markers
        if (output.includes('[PHASE]')) {
            const lines = output.split('\n');
            lines.forEach(line => {
                if (line.trim().startsWith('[PHASE]')) {
                    const status = line.trim().replace('[PHASE] ', '');
                    if (mainWindow) {
                        mainWindow.webContents.send('update-status', status);
                    }
                }
            });
        }
        // Also catch standard docker output for more granular feedback if needed
        // but let's stick to the high-level phases for now.
    });

    dockerProcess.stderr.on('data', (data) => {
        console.error(`Docker Error: ${data}`);
    });

    dockerProcess.on('close', (code) => {
        console.log(`Docker process exited with code ${code}`);
    });

    // Start polling for the server
    checkServerReady();
}

function stopDocker() {
    console.log('Stopping Docker...');
    // execute docker compose down
    exec('wsl docker compose down', { cwd: __dirname }, (error, stdout, stderr) => {
        if (error) {
            console.error(`exec error: ${error}`);
            return;
        }
        console.log(`stdout: ${stdout}`);
        console.error(`stderr: ${stderr}`);
    });

    if (dockerProcess) {
        dockerProcess.kill();
    }
}

app.whenReady().then(() => {
    createWindow();
    startDocker();

    app.on('activate', () => {
        if (BrowserWindow.getAllWindows().length === 0) createWindow();
    });
});

app.on('window-all-closed', () => {
    stopDocker();
    // Wait a bit for docker to stop?
    // Quitting immediately might leave containers running if stopDocker is async.
    // But strictly speaking, for a desktop app, users might expect it to clean up.
    // We'll give it a moment or just quit. 
    // Ideally we should wait for the callback of `exec` but `window-all-closed` is synchronous event usually.
    // We'll set a small timeout before quitting or just call quit inside the callback.

    // For now, let's just loose-fire `docker compose down` and quit. 
    // The `exec` call above launches a separate process which should persist to completion even if main process exits? 
    // No, if main process exits, child might be killed.
    // We will call app.quit() inside the callback.

    // Actually, simpler:
    if (process.platform !== 'darwin') {
        // app.quit(); // We'll move this to the callback of stopDocker if we want to be sure
    }
});

// Build-in quit override to ensure cleanup
app.on('before-quit', (e) => {
    // Attempt cleanup
    // We can't easily block here asynchronously. 
    // We trust stopDocker() triggered in window-all-closed or here.
    stopDocker();
});
