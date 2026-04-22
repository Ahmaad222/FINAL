#!/usr/bin/env bash

# دالة الإيقاف والتنظيف اللي هتشتغل لما تضغط Ctrl + C
cleanup() {
    echo -e "\n🛑 Caught Ctrl+C! Stopping all ZeinaGuard services safely..."
    
    # 1. قفل البرامج
    sudo pkill -f "python" 2>/dev/null
    sudo pkill -f "pnpm" 2>/dev/null
    sudo fuser -k 3000/tcp 2>/dev/null
    sudo fuser -k 5000/tcp 2>/dev/null
    
    echo "🧹 Running automated cleanup..."
    
    # 2. تفريغ محتوى ملفات الـ Logs
    find logs/ -type f -exec truncate -s 0 {} \; 2>/dev/null
    find sensor/data_logs/ -type f -exec truncate -s 0 {} \; 2>/dev/null
    
    # 3. مسح ملفات الكاش بتاعت البايثون
    find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null
    find . -type f -name "*.pyc" -delete 2>/dev/null

    echo "✅ Everything stopped and cleaned successfully. Goodbye!"
    exit 0
}

# ربط الدالة بـ Ctrl + C
trap cleanup SIGINT SIGTERM

echo "🚀 Starting ZeinaGuard..."
mkdir -p logs

# نقفل أي حاجة قديمة معلقة قبل ما نبدأ
sudo pkill -f "python" 2>/dev/null
sudo pkill -f "pnpm" 2>/dev/null

echo "🟢 Starting Frontend (Port 3000)..."
pnpm dev > logs/frontend.log 2>&1 &
FRONTEND_PID=$!

echo "🟢 Starting Backend (Port 5000)..."
(cd backend && ./.venv/bin/python app.py > ../logs/backend.log 2>&1) &
BACKEND_PID=$!

echo "🟢 Starting Sensor (Root)..."
(cd sensor && sudo ./.venv/bin/python main.py > ../logs/sensor.log 2>&1) &
SENSOR_PID=$!

echo "✅ All services are RUNNING in the background."
echo "🌐 Dashboard is live at: http://localhost:3000"
echo "⚠️  Press [Ctrl + C] at any time to shut down and clean up."

# انتظار العمليات عشان التيرمينال يفضل شغال
wait $FRONTEND_PID
wait $BACKEND_PID
wait $SENSOR_PID
