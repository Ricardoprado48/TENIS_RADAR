import { NavLink } from "react-router-dom";

const NAV_ITEMS = [
  { to: "/calendario", label: "Calendário" },
  { to: "/radar", label: "Radar" },
  { to: "/forward", label: "Forward" },
  { to: "/configuracoes", label: "Config" },
];

// Barra inferior no mobile; some no desktop em favor da SideNav.
export default function BottomNav() {
  return (
    <nav className="fixed inset-x-0 bottom-0 z-10 flex border-t border-rule bg-surface md:hidden">
      {NAV_ITEMS.map((item) => (
        <NavLink
          key={item.to}
          to={item.to}
          className={({ isActive }) =>
            `flex-1 py-3 text-center text-xs transition-colors ${isActive ? "text-court" : "text-mist"}`
          }
        >
          {item.label}
        </NavLink>
      ))}
    </nav>
  );
}
