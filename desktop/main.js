const { app, BrowserWindow, Menu, Tray, ipcMain, shell, dialog } = require('electron');
const { spawn } = require('child_process');
const path = require('path');
const http = require('http');

// ─── Config ───────────────────────────────────────────────────────────
const API_PORT = 8080;
const API_URL = `http://127.0.0.1:${API_PORT}`;
const TITAN_ROOT = path.resolve(__dirname, '..');
const VENV_UVICORN = path.join(TITAN_ROOT, 'venv', 'bin', 'uvicorn');
const UVICORN_CMD = require('fs').existsSync(VENV_UVICORN)
  ? VENV_UVICORN
  : 'uvicorn';

let mainWindow = null;
let tray = null;
let serverProc = null;
let serverReady = false;

// ─── Prevent duplicate instances ─────────────────────────────────────
const gotLock = app.requestSingleInstanceLock();
if (!gotLock) {
  app.quit();
} else {
  app.on('second-instance', () => {
    if (mainWindow) {
      if (mainWindow.isMinimized()) mainWindow.restore();
      mainWindow.focus();
    }
  });
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
  // If something is already listening on 8080 (e.g. from systemd), skip.
  const probe = http.get(API_URL, (res) => {
    serverReady = true;
    probe.destroy();
  });
  probe.on('error', () => {
    // Nothing listening — start it ourselves
    const env = {
      ...process.env,
      PYTHONPATH: [
        path.join(TITAN_ROOT, 'server'),
        path.join(TITAN_ROOT, 'core'),
        '/opt/titan/core',
      ].join(':'),
    };
    serverProc = spawn(
      UVICORN_CMD,
      [
        'titan_api:app',
        '--host', '127.0.0.1',
        '--port', String(API_PORT),
        '--workers', '1',
      ],
      { cwd: path.join(TITAN_ROOT, 'server'), env, detached: false }
    );
    serverProc.stdout.on('data', (d) => console.log('[server]', d.toString().trim()));
    serverProc.stderr.on('data', (d) => console.error('[server]', d.toString().trim()));
    serverProc.on('exit', (code) => {
      if (code !== 0 && code !== null) {
        dialog.showErrorBox('Titan Server Error',
          `The backend server exited unexpectedly (code ${code}).\nCheck the terminal for details.`);
      }
    });
  });
}

// ─── Create the browser window ───────────────────────────────────────
async function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1400,
    height: 900,
    minWidth: 900,
    minHeight: 600,
    title: 'Titan V11.3 — Android Console',
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
      <p>Starting backend server…</p>
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
  if (!require('fs').existsSync(iconPath)) return; // skip if no icon
  tray = new Tray(iconPath);
  tray.setToolTip('Titan V11.3 Console');
  tray.setContextMenu(Menu.buildFromTemplate([
    { label: 'Open Console', click: () => { if (mainWindow) mainWindow.show(); else createWindow(); } },
    { type: 'separator' },
    { label: 'Quit Titan', click: () => app.quit() },
  ]));
  tray.on('double-click', () => { if (mainWindow) mainWindow.show(); });
}

// ─── App lifecycle ───────────────────────────────────────────────────
app.whenReady().then(() => {
  startServer();
  createWindow();
  createTray();
});

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit();
});

app.on('activate', () => {
  if (BrowserWindow.getAllWindows().length === 0) createWindow();
});

app.on('before-quit', () => {
  if (serverProc) {
    serverProc.kill('SIGTERM');
    serverProc = null;
  }
});
