'use client';

import { useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { useAuthInit } from '@/hooks/use-auth';

export default function Home() {
  const router = useRouter();
  const { isAuthenticated, isLoading } = useAuthInit();

  useEffect(() => {
    if (!isLoading) {
      // Redirect to dashboard if authenticated, otherwise to login
      if (isAuthenticated) {
        router.push('/dashboard');
      } else {
        router.push('/login');
      }
    }
  }, [isAuthenticated, isLoading, router]);

  return (
    <div className="flex items-center justify-center min-h-screen bg-gradient-to-b from-slate-900 to-slate-950">
      <div className="text-center">
        <h1 className="text-3xl font-bold text-white mb-2">ZeinaGuard Pro</h1>
        <p className="text-slate-400 mb-4">Wireless Intrusion Prevention System</p>
        <p className="text-slate-500">Redirecting...</p>
      </div>
    </div>
  );
}
