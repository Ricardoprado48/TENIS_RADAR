import { NavLink } from "react-router-dom";

const NAV_ITEMS = [
  { to: "/calendario", label: "Calendário" },
  { to: "/radar", label: "Radar" },
  { to: "/forward", label: "Forward Test" },
  { to: "/configuracoes", label: "Configurações" },
];

// Trilha fixa no desktop; some no mobile em favor da BottomNav (barra
// inferior), conforme pedido de navegacao responsiva.
export default function SideNav() {
  return (
    <nav className="hidden shrink-0 flex-col border-r border-rule px-6 py-10 md:flex md:w-56">
      <NavLink to="/" className="mb-10 font-display text-lg font-semibold leading-tight tracking-tight">
        TENNIS
        <br />
        RADAR
      </NavLink>
      <ul className="flex flex-col gap-1">
        {NAV_ITEMS.map((item) => (
          <li key={item.to}>
            <NavLink
              to={item.to}
              className={({ isActive }) =>
                `block border-l-2 py-2 pl-3 text-sm transition-colors ${
                  isActive ? "border-court text-chalk" : "border-transparent text-mist hover:text-chalk"
                }`
              }
            >
              {item.label}
            </NavLink>
          </li>
        ))}
      </ul>
    </nav>
  );
}
