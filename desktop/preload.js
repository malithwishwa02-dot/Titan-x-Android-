// Preload — exposes platform info and setup IPC to renderer.
// The console runs entirely through the API on localhost.
const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('titanDesktop', {
  platform: process.platform,
  version: '11.3.2',
  backend: 'cuttlefish',
  cvd: {
    binDir: process.env.CVD_BIN_DIR || '/opt/titan/cuttlefish/cf/bin',
    homeBase: process.env.CVD_HOME_BASE || '/opt/titan/cuttlefish',
    imagesDir: process.env.CVD_IMAGES_DIR || '/opt/titan/cuttlefish/images',
  },
  // Setup IPC
  getSystemInfo: () => ipcRenderer.invoke('setup:getInfo'),
  runSetup: () => ipcRenderer.invoke('setup:run'),
  launchConsole: () => ipcRenderer.invoke('setup:launch'),
  onSetupProgress: (callback) => {
    ipcRenderer.on('setup:progress', (_event, msg) => callback(msg));
  },
});
