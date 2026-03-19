const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('electronAPI', {
  onStatusUpdate: (callback) => ipcRenderer.on('update-status', (_event, value) => callback(value)),
  onLogAppend: (callback) => ipcRenderer.on('append-log', (_event, value) => callback(value))
});
