const { app, BrowserWindow, Menu, Tray, ipcMain, shell, dialog } = require('electron');
const { spawn, execSync } = require('child_process');
const path = require('path');
const fs = require('fs');
const http = require('http');

// ─── Path Resolution (packaged vs dev) ────────────────────────────────
const IS_PACKAGED = app.isPackaged;
const RESOURCES = IS_PACKAGED ? process.resourcesPath : path.resolve(__dirname, '..');
const USER_DATA = app.getPath('userData');        // ~/.config/titan-console
const TITAN_DATA = path.join(USER_DATA, 'data');
const VENV_DIR = path.join(USER_DATA, 'venv');
const SERVER_DIR = path.join(RESOURCES, 'server');
const CORE_DIR = path.join(RESOURCES, 'core');
const SETUP_DONE = path.join(USER_DATA, '.setup-done');

// ─── Config ───────────────────────────────────────────────────────────
const API_PORT = 8080;
const API_URL = `http://127.0.0.1:${API_PORT}`;

let mainWindow = null;
let setupWindow = null;
let tray = null;
let serverProc = null;

// ─── Prevent duplicate instances ─────────────────────────────────────
const gotLock = app.requestSingleInstanceLock();
if (!gotLock) {
  app.quit();
} else {
  app.on('second-instance', () => {
    const win = mainWindow || setupWindow;
    if (win) {
      if (win.isMinimized()) win.restore();
      win.focus();
    }
  });
}

// ─── Utilities ───────────────────────────────────────────────────────
function ensureDir(d) { fs.mkdirSync(d, { recursive: true }); }

function findPython() {
  for (const cmd of ['python3', 'python']) {
    try {
      const ver = execSync(`${cmd} --version 2>&1`, { timeout: 5000 }).toString().trim();
      const match = ver.match(/Python\s+(\d+)\.(\d+)/);
      if (match && (parseInt(match[1]) > 3 || (parseInt(match[1]) === 3 && parseInt(match[2]) >= 10))) {
        return { cmd, version: ver };
      }
    } catch (_) { /* not found */ }
  }
  return null;
}

function getUvicornCmd() {
  // Prefer venv uvicorn if it exists
  const venvUvi = path.join(VENV_DIR, 'bin', 'uvicorn');
  if (fs.existsSync(venvUvi)) return venvUvi;
  // Fallback: system-installed or legacy /opt/titan/venv
  const legacyUvi = path.join(RESOURCES, 'venv', 'bin', 'uvicorn');
  if (fs.existsSync(legacyUvi)) return legacyUvi;
  return 'uvicorn';
}

function isSetupDone() {
  return fs.existsSync(SETUP_DONE) && fs.existsSync(path.join(VENV_DIR, 'bin', 'uvicorn'));
}

// ─── Poll until the API server is accepting connections ───────────────
function waitForServer(retries = 40, interval = 500) {
  return new Promise((resolve, reject) => {
    let attempts = 0;
    const check = () => {
      const req = http.get(API_URL, (res) => { resolve(); req.destroy(); });
      req.on('error', () => {
        attempts++;
        if (attempts >= retries) return reject(new Error('Server did not start'));
        setTimeout(check, interval);
      });
      req.setTimeout(400, () => req.destroy());
    };
    check();
  });
}

// ─── Start the uvicorn/FastAPI backend ───────────────────────────────
function startServer() {
  return new Promise((resolve) => {
    // If something is already listening on 8080 (e.g. from systemd), skip.
    const probe = http.get(API_URL, (res) => {
      probe.destroy();
      resolve(true);
    });
    probe.on('error', () => {
      // Nothing listening — start it ourselves
      const env = {
        ...process.env,
        PYTHONPATH: [SERVER_DIR, CORE_DIR, '/opt/titan/core'].join(':'),
        TITAN_DATA,
        CVD_BIN_DIR: process.env.CVD_BIN_DIR || '/opt/titan/cuttlefish/cf/bin',
        CVD_HOME_BASE: process.env.CVD_HOME_BASE || '/opt/titan/cuttlefish',
        CVD_IMAGES_DIR: process.env.CVD_IMAGES_DIR || '/opt/titan/cuttlefish/images',
      };

      serverProc = spawn(
        getUvicornCmd(),
        [
          'titan_api:app',
          '--host', '127.0.0.1',
          '--port', String(API_PORT),
          '--workers', '1',
        ],
        { cwd: SERVER_DIR, env, detached: false }
      );
      serverProc.stdout.on('data', (d) => console.log('[server]', d.toString().trim()));
      serverProc.stderr.on('data', (d) => console.error('[server]', d.toString().trim()));
      serverProc.on('exit', (code) => {
        if (code !== 0 && code !== null) {
          dialog.showErrorBox('Titan Server Error',
            `The backend server exited unexpectedly (code ${code}).\nCheck the terminal for details.`);
        }
      });
      resolve(false);
    });
    probe.setTimeout(2000, () => { probe.destroy(); });
  });
}

// ─── Setup Window (first-run) ────────────────────────────────────────
function showSetupWindow() {
  setupWindow = new BrowserWindow({
    width: 600,
    height: 520,
    title: 'Titan Console — Setup',
    backgroundColor: '#0a0e17',
    icon: path.join(__dirname, 'assets', 'icon.png'),
    resizable: false,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      nodeIntegration: false,
      contextIsolation: true,
    },
    autoHideMenuBar: true,
  });

  setupWindow.loadFile(path.join(__dirname, 'setup.html'));
  setupWindow.on('closed', () => { setupWindow = null; });
}

// ─── IPC Handlers ────────────────────────────────────────────────────
ipcMain.handle('setup:getInfo', () => {
  const python = findPython();
  const kvmExists = fs.existsSync('/dev/kvm');
  let adbFound = false;
  try { execSync('which adb', { timeout: 3000 }); adbFound = true; } catch (_) {}
  return {
    python: python ? python : null,
    kvm: kvmExists,
    adb: adbFound,
    venvExists: fs.existsSync(path.join(VENV_DIR, 'bin', 'python3')),
    dataDir: TITAN_DATA,
    venvDir: VENV_DIR,
    isPackaged: IS_PACKAGED,
  };
});

ipcMain.handle('setup:run', async (event) => {
  const python = findPython();
  if (!python) return { ok: false, error: 'Python 3.10+ not found. Install python3 and try again.' };

  const send = (msg) => {
    if (setupWindow && !setupWindow.isDestroyed()) {
      setupWindow.webContents.send('setup:progress', msg);
    }
  };

  try {
    // 1. Create data directories
    send('Creating data directories...');
    ensureDir(TITAN_DATA);
    ensureDir(path.join(TITAN_DATA, 'devices'));
    ensureDir(path.join(TITAN_DATA, 'profiles'));
    ensureDir(path.join(TITAN_DATA, 'config'));
    ensureDir(path.join(TITAN_DATA, 'forge_gallery'));

    // 2. Copy .env if not exists
    const envPath = path.join(USER_DATA, '.env');
    if (!fs.existsSync(envPath)) {
      const envExample = path.join(RESOURCES, '.env.example');
      if (fs.existsSync(envExample)) {
        fs.copyFileSync(envExample, envPath);
        send('Created .env from template');
      }
    }

    // 3. Create Python virtual environment
    send('Creating Python virtual environment...');
    if (!fs.existsSync(path.join(VENV_DIR, 'bin', 'python3'))) {
      execSync(`${python.cmd} -m venv "${VENV_DIR}"`, { timeout: 60000 });
    }
    send('Virtual environment ready');

    // 4. Install pip dependencies
    send('Installing Python dependencies (this may take a minute)...');
    const pipCmd = path.join(VENV_DIR, 'bin', 'pip');
    const reqFile = path.join(RESOURCES, 'server', 'requirements.txt');
    if (fs.existsSync(reqFile)) {
      execSync(`"${pipCmd}" install --upgrade pip -q`, { timeout: 120000 });
      execSync(`"${pipCmd}" install -r "${reqFile}" -q`, { timeout: 300000 });
    }
    send('Dependencies installed');

    // 5. Mark setup as done
    fs.writeFileSync(SETUP_DONE, JSON.stringify({
      version: '11.3.2',
      python: python.version,
      timestamp: new Date().toISOString(),
    }));
    send('Setup complete!');
    return { ok: true };
  } catch (err) {
    send('Error: ' + err.message);
    return { ok: false, error: err.message };
  }
});

ipcMain.handle('setup:launch', async () => {
  // Close setup window, start server, open main console
  if (setupWindow) setupWindow.close();
  startServer();
  await createMainWindow();
});

// ─── Main Console Window ─────────────────────────────────────────────
async function createMainWindow() {
  mainWindow = new BrowserWindow({
    width: 1400,
    height: 900,
    minWidth: 900,
    minHeight: 600,
    title: 'Titan V11.3 — Cuttlefish Android Console',
    backgroundColor: '#0a0e17',
    icon: path.join(__dirname, 'assets', 'icon.png'),
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      nodeIntegration: false,
      contextIsolation: true,
    },
    show: false,
    autoHideMenuBar: true,
  });

  // Show a loading screen while the server starts
  mainWindow.loadURL('data:text/html,' + encodeURIComponent(`
    <!DOCTYPE html>
    <html>
    <head>
      <meta charset="UTF-8">
      <style>
        body { margin:0; background:#0a0e17; display:flex; flex-direction:column;
               align-items:center; justify-content:center; height:100vh; font-family:system-ui; }
        .logo { width:64px; height:64px; background:linear-gradient(135deg,#06b6d4,#3b82f6);
                border-radius:16px; display:flex; align-items:center; justify-content:center;
                font-size:32px; font-weight:800; color:#fff; margin-bottom:24px; }
        h1 { color:#00d4ff; font-size:22px; margin:0 0 8px; }
        p  { color:#64748b; font-size:14px; margin:0 0 24px; }
        .spinner { width:36px; height:36px; border:3px solid #1e293b;
                   border-top-color:#00d4ff; border-radius:50%; animation:spin 0.8s linear infinite; }
        @keyframes spin { to { transform:rotate(360deg); } }
      </style>
    </head>
    <body>
      <div class="logo">T</div>
      <h1>Titan V11.3</h1>
      <p>Starting Cuttlefish backend server…</p>
      <div class="spinner"></div>
    </body>
    </html>
  `));
  mainWindow.show();

  // Wait for server then load the console
  try {
    await waitForServer();
    mainWindow.loadURL(API_URL);
  } catch (err) {
    mainWindow.loadURL('data:text/html,' + encodeURIComponent(`
      <!DOCTYPE html>
      <html>
      <head><meta charset="UTF-8">
      <style>body{margin:0;background:#0a0e17;display:flex;flex-direction:column;
        align-items:center;justify-content:center;height:100vh;font-family:system-ui;}
        h1{color:#ef4444;font-size:20px;} p{color:#94a3b8;font-size:13px;max-width:480px;text-align:center;}</style>
      </head>
      <body>
        <h1>⚠ Server not reachable</h1>
        <p>Could not connect to the Titan API on port ${API_PORT}.<br>
        Start the server manually with:<br><code style="color:#00d4ff">uvicorn titan_api:app --port ${API_PORT}</code>
        then relaunch the app.</p>
      </body></html>
    `));
  }

  mainWindow.on('closed', () => { mainWindow = null; });

  // Open external links in the system browser
  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    if (!url.startsWith(`http://127.0.0.1:${API_PORT}`)) {
      shell.openExternal(url);
      return { action: 'deny' };
    }
    return { action: 'allow' };
  });
}

// ─── System tray ─────────────────────────────────────────────────────
function createTray() {
  const iconPath = path.join(__dirname, 'assets', 'tray.png');
  if (!fs.existsSync(iconPath)) return;
  tray = new Tray(iconPath);
  tray.setToolTip('Titan V11.3 Cuttlefish Console');
  tray.setContextMenu(Menu.buildFromTemplate([
    { label: 'Open Console', click: () => { if (mainWindow) mainWindow.show(); else createMainWindow(); } },
    { type: 'separator' },
    { label: 'Quit Titan', click: () => app.quit() },
  ]));
  tray.on('double-click', () => { if (mainWindow) mainWindow.show(); });
}

// ─── App lifecycle ───────────────────────────────────────────────────
app.whenReady().then(async () => {
  createTray();

  if (isSetupDone()) {
    // Normal launch — start server and show console
    startServer();
    await createMainWindow();
  } else {
    // First run — show setup wizard
    showSetupWindow();
  }
});

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit();
});

app.on('activate', () => {
  if (BrowserWindow.getAllWindows().length === 0) {
    if (isSetupDone()) createMainWindow();
    else showSetupWindow();
  }
});

app.on('before-quit', () => {
  if (serverProc) {
    serverProc.kill('SIGTERM');
    serverProc = null;
  }
});
