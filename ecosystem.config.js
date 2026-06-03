module.exports = {
  apps: [
    {
      name: "xaugold3-bot",
      script: "live_trader.py",
      interpreter: "C:\\Users\\Mako by Seris\\AppData\\Local\\Programs\\Python\\Python314\\python.exe",
      cwd: "F:\\XAUGOLD 3",
      // Auto-restart settings
      autorestart: true,
      max_restarts: 50,
      min_uptime: "10s",        // Anggap crash jika mati dalam <10 detik
      restart_delay: 10000,      // Delay 10 detik sebelum restart setelah crash
      // Environment
      env: {
        PYTHONIOENCODING: "utf-8",
        PYTHONUNBUFFERED: "1",   // Supaya log real-time (tidak di-buffer)
      },
      // Log settings
      log_date_format: "YYYY-MM-DD HH:mm:ss",
      error_file: "F:\\XAUGOLD 3\\pm2-error.log",
      out_file: "F:\\XAUGOLD 3\\pm2-out.log",
      merge_logs: true,
      // Tidak perlu watch (bot sudah loop sendiri)
      watch: false,
    }
  ]
};
