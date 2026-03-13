// Minimal preload — exposes nothing sensitive.
// The console runs entirely through the API on localhost.
const { contextBridge } = require('electron');

contextBridge.exposeInMainWorld('titanDesktop', {
  platform: process.platform,
  version: '11.3.1',
});
