const { app, BrowserWindow } = require("electron"); console.log("app type:", typeof app); app.whenReady().then(() => { console.log("App ready!"); app.quit(); });
