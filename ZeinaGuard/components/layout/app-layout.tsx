'use client';

import { ReactNode } from 'react';
import { Sidebar } from './sidebar';
import { CommandPalette } from '../command-palette';

interface AppLayoutProps {
  children: ReactNode;
}

export function AppLayout({ children }: AppLayoutProps) {
  return (
    <div className="flex min-h-screen bg-slate-900">
      <Sidebar />
      <main className="flex-1 ml-64 bg-slate-900">
        {children}
      </main>
      <CommandPalette />
    </div>
  );
}
