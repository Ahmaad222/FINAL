#event_bus.py
from queue import Queue

# الطابور الأساسي اللي الـ Sniffer بيرمي فيه والـ ThreatManager بيسحب منه
event_queue = Queue()

# ---------------------------------------------------------
# الطوابير الخاصة بالتهديدات المؤكدة (الـ ThreatManager هيرمي في الاتنين)
# ---------------------------------------------------------

# 1. طابور الأكشن: الـ ResponseEngine بيسحب منه عشان ينفذ الـ Deauth Attack
containment_queue = Queue()

# 2. طابور المراقبة: الـ WSClient بيسحب منه عشان يبعت التهديد للـ Backend في الـ Real-time
dashboard_queue = Queue()