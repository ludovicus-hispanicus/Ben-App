const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('electronAPI', {
  onStatusUpdate: (callback) => ipcRenderer.on('update-status', (_event, value) => callback(value))
});
