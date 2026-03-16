'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { useAuth } from '@/hooks/use-auth';
import {
  LayoutDashboard,
  AlertTriangle,
  Wifi,
  Bell,
  BarChart3,
  LogOut,
  Settings,
} from 'lucide-react';

export function Sidebar() {
  const pathname = usePathname();
  const { user, logout } = useAuth();

  const menuItems = [
    { href: '/dashboard', label: 'Dashboard', icon: LayoutDashboard },
    { href: '/threats', label: 'Threats', icon: AlertTriangle },
    { href: '/sensors', label: 'Sensors', icon: Wifi },
    { href: '/alerts', label: 'Alerts', icon: Bell },
    { href: '/incidents', label: 'Incidents', icon: BarChart3 },
  ];

  return (
    <aside className="fixed left-0 top-0 h-screen w-64 bg-slate-900 border-r border-slate-800 flex flex-col">
      {/* Logo */}
      <div className="p-6 border-b border-slate-800">
        <h2 className="text-2xl font-bold text-white flex items-center gap-2">
          <AlertTriangle className="w-6 h-6 text-blue-500" />
          ZeinaGuard
        </h2>
        <p className="text-xs text-slate-500 mt-1">Wireless IPS</p>
      </div>

      {/* Navigation */}
      <nav className="flex-1 p-4 space-y-2">
        {menuItems.map((item) => {
          const Icon = item.icon;
          const isActive = pathname === item.href;

          return (
            <Link
              key={item.href}
              href={item.href}
              className={`flex items-center gap-3 px-4 py-3 rounded-lg transition-colors ${
                isActive
                  ? 'bg-blue-600 text-white'
                  : 'text-slate-400 hover:text-white hover:bg-slate-800'
              }`}
            >
              <Icon className="w-5 h-5" />
              <span className="font-medium">{item.label}</span>
            </Link>
          );
        })}
      </nav>

      {/* Footer */}
      <div className="p-4 border-t border-slate-800 space-y-2">
        <div className="px-4 py-2 text-sm">
          <p className="text-slate-500">Logged in as</p>
          <p className="text-white font-medium">{user?.username}</p>
        </div>
        <button
          onClick={logout}
          className="w-full flex items-center gap-2 px-4 py-2 text-slate-400 hover:text-white hover:bg-slate-800 rounded-lg transition-colors"
        >
          <LogOut className="w-4 h-4" />
          <span className="text-sm">Logout</span>
        </button>
      </div>
    </aside>
  );
}
