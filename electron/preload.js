const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('electronAPI', {
  onStatusUpdate: (callback) => ipcRenderer.on('update-status', (_event, value) => callback(value)),
  onLogAppend: (callback) => ipcRenderer.on('append-log', (_event, value) => callback(value)),
  onVersion: (callback) => ipcRenderer.on('splash-version', (_event, value) => callback(value)),
  // Native folder picker — resolves to the chosen absolute path, or null if cancelled.
  pickDirectory: () => ipcRenderer.invoke('pick-directory')
});
