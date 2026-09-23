import { Outlet } from "react-router-dom";
import SideNav from "../components/SideNav";
import BottomNav from "../components/BottomNav";

export default function AppLayout() {
  return (
    <div className="flex min-h-screen bg-ink text-chalk">
      <SideNav />
      <main className="w-full max-w-2xl flex-1 px-6 pb-24 pt-10 md:px-12 md:pb-10">
        <Outlet />
      </main>
      <BottomNav />
    </div>
  );
}
